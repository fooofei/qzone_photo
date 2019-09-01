package main

import (
	"bytes"
	"context"
	"encoding/gob"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"io/ioutil"
	"log"
	"math/rand"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/zellyn/kooky"
)

type album struct {
	ID    string // in qzone response json
	Name  string // in qzone response json
	Total int    // in qzone response json
}

func (ab *album) String() string {
	return fmt.Sprintf("ID=%v Name=%v Total=%v",
		ab.ID, ab.Name, ab.Total)
}

type photo struct {
	RawUri     string
	NormalUri  string
	InAbIdx    int
	Name       string
	OwnerAlbum *album
	SavedName  string
}

func (p *photo) String() string {
	return fmt.Sprintf("Name=%v InAbIdx=%v RawUri=%v SavedName=%v (%v)",
		p.Name, p.InAbIdx, p.RawUri, p.SavedName, p.OwnerAlbum)
}

type qpContext struct {
	WaitCtx           context.Context // 提供强制关闭的功能
	WaitWg            *sync.WaitGroup // 等待所有routine 退出
	PhotoCh           chan *photo     // photo 队列
	ErrorsCh          chan error      // 错误的缓存
	PhotoCnt          uint32          // photo 写到文件的个数
	CurDir            string          // 工作目录
	Jar               http.CookieJar  // 浏览器cookies
	QzoneGTK          int             // uri中的参数
	MyQid             string
	TargetQid         string
	TaskDoneCh        chan bool // 任务结束的通知
	Aria2SessionFile  string    // aria2 下载队列文件
	ChromeCookiesFile string    // chrome cookies 路径
	Aria2ConfFile     string    // aria2 配置文件 aria2 第一入口
}

func (q *qpContext) Status() string {
	b := new(bytes.Buffer)
	_, _ = fmt.Fprintf(b, "len(PhotoCh)=%v ", len(q.PhotoCh))
	_, _ = fmt.Fprintf(b, "PhotoCnt=%v ", q.PhotoCnt)
	return b.String()
}

func newQzoneHttpClt(ctx *qpContext) *http.Client {
	clt := new(http.Client)
	clt.Jar = ctx.Jar
	return clt
}

func nonblockEnqError(ctx *qpContext, err error) {
	// If tell exit, then not push error anymore
	select {
	case <-ctx.WaitCtx.Done():
		return
	default:
	}
	select {
	case ctx.ErrorsCh <- err:
	default:
	}
}

func writePhotoAria2Fmt(ctx *qpContext, w io.Writer, p *photo) {
	uri := p.RawUri
	if uri == "" {
		uri = p.NormalUri
	}

	p.SavedName = filepath.Join(ctx.CurDir,
		ctx.TargetQid, fmt.Sprintf("%v_%v_%v.png", p.OwnerAlbum.Name, p.Name, p.InAbIdx))

	newCnt := atomic.AddUint32(&ctx.PhotoCnt, 1)
	_, _ = fmt.Fprintf(w, "# %v\n", newCnt)
	_, _ = fmt.Fprintf(w, "# rawUri=%v\n", p.RawUri)
	_, _ = fmt.Fprintf(w, "# normalUri=%v\n", p.NormalUri)
	_, _ = fmt.Fprintf(w, "%v\n", uri)
	_, _ = fmt.Fprintf(w, "  dir=/\n")
	_, _ = fmt.Fprintf(w, "  out=%v\n", p.SavedName)
	_, _ = fmt.Fprintf(w, "\n")
}

func waitPhoto(ctx *qpContext) {
	var p *photo
	var err error
	var cnt int
	_ = err
	var ok bool

	// If not exist will create new one, if exist will truncate
	fw, err := os.Create(ctx.Aria2SessionFile)
	if err != nil {
		log.Panic(err)
	}

	_, _ = fmt.Fprintf(fw, "# Generated by QzonePhoto, Do not Edit it.\n")

loop:
	for {
		select {
		case <-ctx.WaitCtx.Done():
			break loop
		case p, ok = <-ctx.PhotoCh:
			if !ok {
				break loop
			}

		}
		writePhotoAria2Fmt(ctx, fw, p)
		cnt++
	}
	_ = fw.Close()
	close(ctx.TaskDoneCh)
}

func setupSignal(ctx *qpContext, cancel context.CancelFunc) {

	ch := make(chan os.Signal, 1)
	signal.Notify(ch, os.Interrupt)
	signal.Notify(ch, syscall.SIGTERM)

	ctx.WaitWg.Add(1)
	go func() {
		select {
		case <-ch:
			cancel()
		case <-ctx.WaitCtx.Done():
		case <-ctx.TaskDoneCh:
		}
		ctx.WaitWg.Done()
	}()
}

// From qqlib/qzone.py
func makeGTKFromKey(p_skey string) int {
	h := 5381
	_ = h

	for _, v := range p_skey {
		h += (h << 5) + int(v)
	}

	h = h & 0x7fffffff
	return h
}
func initGTK(cookies []*http.Cookie, ctx *qpContext) {

	s_key := ""
	p_skey := ""
	for _, cookie := range cookies {

		if cookie.Domain == ".qq.com" && cookie.Name == "skey" {
			s_key = cookie.Value
			break

		} else if strings.Contains(cookie.Domain, "qzone.qq.com") && cookie.Name == "p_skey" {
			p_skey = cookie.Value
			break
		}
	}
	// first use p_skey
	if p_skey != "" {
		ctx.QzoneGTK = makeGTKFromKey(p_skey)
	} else if s_key != "" {
		ctx.QzoneGTK = makeGTKFromKey(s_key)
	}

}

func parseCookies(rawUrl string, cks []*http.Cookie, jar *cookiejar.Jar, ctx *qpContext) error {
	u, err := url.Parse(rawUrl)
	if err != nil {
		return err
	}

	jar.SetCookies(u, cks)
	// cannot use jar.Cookies(u) for search `p_skey`
	// the cookie.Domain will be clean, cannot use for match
	return nil
}

func dupChromeCookies(ctx *qpContext) (http.CookieJar, error) {
	// use cache

	var cookies []*http.Cookie

	var err error
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}
	localCacheFile := filepath.Join(ctx.CurDir, "ckcache")

	if _, err = os.Stat(localCacheFile); os.IsNotExist(err) {

		kkyCookies, err := kooky.ReadChromeCookies(ctx.ChromeCookiesFile, "", "", time.Time{})
		if err != nil {
			return nil, err
		}
		cks := make([]*http.Cookie, 0)
		for _, cookie := range kkyCookies {
			v := cookie.HttpCookie()
			cks = append(cks, &v)
		}

		fw, err := os.Create(localCacheFile)
		if err != nil {
			return nil, err
		}
		defer func() {
			_ = fw.Close()
		}()
		enc := gob.NewEncoder(fw)
		err = enc.Encode(cks)
		if err != nil {
			return nil, err
		}
		log.Printf("Dup Chrome Cookies to %v", localCacheFile)
	}
	log.Printf("Load Cookies from cache file %v", localCacheFile)
	fr, err := os.Open(localCacheFile)
	dec := gob.NewDecoder(fr)
	err = dec.Decode(&cookies)
	if err != nil {
		return nil, err
	}
	// TODO:you can comment it for use a cache
	// remove the file will not keep cache
	_ = os.Remove(localCacheFile)

	err = parseCookies("https://www.qzone.qq.com", cookies, jar, ctx)
	if err != nil {
		return nil, err
	}
	err = parseCookies("https://www.user.qzone.qq.com", cookies, jar, ctx)
	if err != nil {
		return nil, err
	}
	err = parseCookies("https://www.qzs.qq.com", cookies, jar, ctx)
	if err != nil {
		return nil, err
	}
	err = parseCookies("https://www.qq.com", cookies, jar, ctx)
	if err != nil {
		return nil, err
	}
	initGTK(cookies, ctx)
	return jar, nil
}

func queryAlbums(ctx *qpContext) ([]*album, error) {
	uri := fmt.Sprintf("https://h5.qzone.qq.com/proxy/domain"+
		"/tjalist.photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3"+
		"?g_tk=%v&t=%v&hostUin=%v&uin=%v"+
		"&appid=4&inCharset=utf-8&outCharset=utf-8&source=qzone"+
		"&plat=qzone&format=jsonp&callbackFun=&mode=2&pageStart=0&pageNum=1000",
		ctx.QzoneGTK, rand.Int(), ctx.TargetQid, ctx.MyQid)

	clt := newQzoneHttpClt(ctx)
	req, err := http.NewRequest("GET", uri, nil)
	if err != nil {
		return nil, err
	}
	req = req.WithContext(ctx.WaitCtx)
	resp, err := clt.Do(req)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != 200 {
		_ = resp.Body.Close()
		return nil, fmt.Errorf("resp.statusCode=%v", resp.StatusCode)
	}
	m, err := handleQzoneResp(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		return nil, err
	}
	// albumListModeSort maybe
	albumList, _ := m["albumList"].([]interface{})
	albums := make([]*album, 0)
	for _, a0 := range albumList {
		a, _ := a0.(map[string]interface{})
		pa := &album{}
		pa.ID, _ = a["id"].(string)
		pa.Name, _ = a["name"].(string)
		total0, _ := a["total"].(float64)
		pa.Total = int(total0)
		albums = append(albums, pa)
	}
	return albums, nil
}

func handleQzoneResp(r io.Reader) (map[string]interface{}, error) {
	rc, err := ioutil.ReadAll(r)
	if err != nil {
		return nil, err
	}
	rcs := string(rc)
	pref := "_Callback("
	suff := ");"
	if !(strings.HasPrefix(rcs, pref) &&
		strings.HasSuffix(rcs, suff)) {
		return nil, fmt.Errorf("invalid %v", rcs)
	}
	rcs = strings.TrimPrefix(rcs, pref)
	rcs = strings.TrimSuffix(rcs, suff)

	m := make(map[string]interface{}, 0)

	err = json.Unmarshal([]byte(rcs), &m)
	if err != nil {
		return nil, fmt.Errorf("%v, invalid %v", err, rcs)
	}
	code, _ := m["code"].(float64)
	subcode := m["subcode"].(float64)
	if !(int(code) == 0 && int(subcode) == 0) {
		msg, _ := m["message"].(string)
		return nil, fmt.Errorf("%v", msg)
	}
	subm, _ := m["data"].(map[string]interface{})
	return subm, nil
}

func queryPhotos(ctx *qpContext, ab *album) {
	var ok bool
	// get first photo for raw photo
	uri1 := fmt.Sprintf("https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"+
		"cgi_list_photo?g_tk=%v&t=%v&mode=0&idcNum=5&hostUin=%v"+
		"&topicId=%v&noTopic=0&uin=%v&pageStart=0&pageNum=9000"+
		"&inCharset=utf-8&outCharset=utf-8&source=qzone&plat=qzone"+
		"&outstyle=json&format=jsonp&json_esc=1",
		ctx.QzoneGTK, rand.Int(), ctx.TargetQid, ab.ID, ctx.MyQid)

	clt := newQzoneHttpClt(ctx)
	req, err := http.NewRequest("GET", uri1, nil)
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}
	req = req.WithContext(ctx.WaitCtx)
	resp, err := clt.Do(req)
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}

	if resp.StatusCode != 200 {
		nonblockEnqError(ctx, fmt.Errorf("resp.StatusCode = %v", resp.StatusCode))
		_ = resp.Body.Close()
		return
	}

	m, err := handleQzoneResp(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}

	photoList, _ := m["photoList"].([]interface{})
	if len(photoList) <= 0 {
		if ab.Total > 0 {
			nonblockEnqError(ctx, fmt.Errorf("ab=%v but len=0", ab))
		}
		return
	}
	p, _ := photoList[0].(map[string]interface{})
	lloc, _ := p["lloc"].(string)

	uri2 := fmt.Sprintf("https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com"+
		"/fcgi-bin/cgi_floatview_photo_list_v2?"+
		"g_tk=%v&t=%v&topicId=%v&picKey=%v"+
		"&shootTime=&cmtOrder=1&fupdate=1&plat=qzone&source=qzone"+
		"&cmtNum=10&inCharset=utf-8&outCharset=utf-8&offset=0"+
		"&uin=%v&appid=4&isFirst=1&hostUin=%v&postNum=9999",
		ctx.QzoneGTK, rand.Int(), ab.ID, lloc, ctx.MyQid, ctx.TargetQid)

	req, err = http.NewRequest("GET", uri2, nil)
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}
	resp, err = clt.Do(req)
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}
	
	if resp.StatusCode != 200 {
		nonblockEnqError(ctx, fmt.Errorf("resp.StatusCode = %v", resp.StatusCode))
		_ = resp.Body.Close()
		return
	}

	m, err = handleQzoneResp(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		nonblockEnqError(ctx, err)
		return
	}

	ptos, _ := m["photos"].([]interface{})

	for idx, pto0 := range ptos {
		pto, _ := pto0.(map[string]interface{})
		p := new(photo)
		p.OwnerAlbum = ab
		p.Name, _ = pto["name"].(string)
		p.InAbIdx = idx

		if p.RawUri, ok = pto["raw"].(string); ok {

		} else if p.RawUri, ok = pto["origin"].(string); ok {
		}
		p.NormalUri, _ = pto["url"].(string)

		// you can filter photos here

		select {
		case <-ctx.WaitCtx.Done():
			return
		case ctx.PhotoCh <- p:
		}
	}

}

func makeAria2Conf(ctx *qpContext) {
	fw, err := os.Create(ctx.Aria2ConfFile)
	if err != nil {
		log.Panic(err)
	}
	_, _ = fmt.Fprintf(fw, "# Generated by QzonePhoto, Do Not Edit.\n")
	_, _ = fmt.Fprintf(fw, "enable-rpc=true\n")
	_, _ = fmt.Fprintf(fw, "rpc-allow-origin-all=true\n")
	_, _ = fmt.Fprintf(fw, "rpc-listen-all=true\n")
	_, _ = fmt.Fprintf(fw, "max-concurrent-downloads=100\n")
	_, _ = fmt.Fprintf(fw, "auto-file-renaming=false\n")
	_, _ = fmt.Fprintf(fw, "continue=true\n") // 断点续传
	_, _ = fmt.Fprintf(fw, "split=5\n")
	_, _ = fmt.Fprintf(fw, "load-cookies=%v\n", ctx.ChromeCookiesFile)
	_, _ = fmt.Fprintf(fw, "input-file=%v\n", ctx.Aria2SessionFile)
	_ = fw.Close()
}

func main() {

	ctx := new(qpContext)
	var err error
	var cancel context.CancelFunc

	flag.StringVar(&ctx.MyQid, "self", "", "self qq")
	flag.StringVar(&ctx.TargetQid, "target", "", "target qq")

	flag.Parse()
	if !(ctx.MyQid != "" && ctx.TargetQid != "") {
		flag.PrintDefaults()
		return
	}

	log.SetPrefix(fmt.Sprintf("pid= %v ", os.Getpid()))
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	ctx.WaitWg = new(sync.WaitGroup)
	ctx.WaitCtx, cancel = context.WithCancel(context.Background())
	curFilePath, _ := os.Executable()
	ctx.CurDir = filepath.Dir(curFilePath)
	log.Printf("curdir= %v", ctx.CurDir)
	ctx.Aria2SessionFile = filepath.Join(ctx.CurDir, "qzone.aria2.session")
	ctx.Aria2ConfFile = filepath.Join(ctx.CurDir, "aria2.conf")
	usr, _ := user.Current()
	ctx.ChromeCookiesFile =
		fmt.Sprintf("%s/Library/Application Support/Google/Chrome/Default/Cookies",
			usr.HomeDir)

	ctx.TaskDoneCh = make(chan bool)
	setupSignal(ctx, cancel)

	jar, err := dupChromeCookies(ctx)
	if err != nil {
		log.Printf("err= %v", err)
	}
	ctx.Jar = jar
	ctx.PhotoCh = make(chan *photo, 10*1000)
	ctx.ErrorsCh = make(chan error, 10)

	abs, err := queryAlbums(ctx)
	if err != nil {
		log.Printf("got err= %v", err)
	}
	log.Printf("got albums count=%v", len(abs))
	// every album can start a separate go routine
	// so we need a complete notify
	absWaitWg := new(sync.WaitGroup)
	calcAllPhotoCnt := 0
	for _, ab := range abs {
		ctx.WaitWg.Add(1)
		absWaitWg.Add(1)
		log.Printf("query photos for %v", ab)
		calcAllPhotoCnt += ab.Total
		go func(ctx *qpContext, ab *album) {
			queryPhotos(ctx, ab)
			ctx.WaitWg.Done()
			absWaitWg.Done()
		}(ctx, ab)
	}
	log.Printf("sum all photo count=%v", calcAllPhotoCnt)
	ctx.WaitWg.Add(1)
	go func() {
		absWaitWg.Wait()
		// when all queryAlbums done, close channel
		log.Printf("All albums done, no more photos")
		close(ctx.PhotoCh)
		ctx.WaitWg.Done()
	}()

	ctx.WaitWg.Add(1)
	go func() {
		waitPhoto(ctx)
		ctx.WaitWg.Done()
	}()

statLoop:
	for {
		select {
		case <-time.After(time.Second * 3):
			log.Printf("%v", ctx.Status())
		case err = <-ctx.ErrorsCh:
			log.Printf("err= %v", err)
		case <-ctx.WaitCtx.Done():
			break statLoop
		case <-ctx.TaskDoneCh:
			break statLoop
		}
	}
	log.Printf("wait exit")
	ctx.WaitWg.Wait()
	log.Printf("%v", ctx.Status())
	makeAria2Conf(ctx)
	log.Printf("Run this in command line: aria2c --conf-path=%v",
		ctx.Aria2ConfFile)
	log.Printf("main exit")
}
