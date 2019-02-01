# -*- coding: UTF-8 -*-

'''
 python 2.7

 使用前请确保以下模块已安装
 pip install requests
 pip install qqlib
 pip install futures

 对比过:
 https://github.com/doctor305/test2/blob/master/QQ.py
 https://github.com/youngytj/Qzone_Photo
 https://github.com/baocaixiong/learnPy/blob/master/Get_QQ_Photo.py

 都不能满足需求，自己就写了个

 下载文件的保存，请见 func_save_photo 中的函数头注释

'''

# ------------------------------------------------------------------------------
# feedback :
# CHANGELOG:
# 2017-02-10 v1.00 fooofei: first version
# 2017-02-12 v2.00 fooofei: 找到原图 API ，可以下载原图了
# 2017-02-20 v2.10 fooofei: 修复 @paukey 反馈的文件保存路径非法问题
# 2017-02-20 v2.20 fooofei: 修复 @Lodour 反馈的 _get_cookie KeyError 问题，旧 API 已经弃用，关闭此代码
# 2017-05-01 v2.30 fooofei: update url, 可能是升级了 https
# 2017-05-09 v3.00 fooofei: 修复 @youngytj 反馈的因为目标 QQ 设置相册视图不同导致无法获取相册的问题

# __version__ = ''

import qqlib
import os
import requests
from qqlib import qzone
from collections import namedtuple
from io_in_out import *
import random

curpath = os.path.dirname(os.path.realpath(__file__))
curpath = io_in_arg(curpath)

#
# 实体类
QzoneAlbum = namedtuple('QzoneAlbum',
                        ['uid', 'name', 'count'])

QzonePhoto = namedtuple('QzonePhoto',
                        ['url', 'name', 'album'])


def func_save_dir(user):
    '''
    提供下载的文件保存在哪
    保存至 <脚本目录>\qzone_photo\<用户QQ> 目录
    :return:
    '''
    return os.path.join(curpath, u'qzone_photo', u'{0}'.format(user))


def func_save_photo_net_helper(session, url, timeout):
    '''
    辅助函数，先用带会话的 session 尝试下载，如果不行就去掉会话尝试下载
    :param session:
    :param url:
    :param timeout:
    :return:
    '''
    if session:
        # 使用已经登陆过的账户下载，不然加密的照片下载都是写着“加密照片”
        # 使用 post 还不行，要用 get
        try:
            return session.get(url, timeout=timeout)
        except requests.ReadTimeout:
            try:
                return session.post(url, timeout=timeout)
            except requests.ReadTimeout:
                return func_save_photo_net_helper(None, url, timeout)
    else:
        return requests.get(url, timeout=timeout)


def func_save_photo(arg):
    '''
    线程函数，运行在线程池中
    文件保存格式 <相册名字>_<文件在相册的索引数字>_<文件名字>.jpeg

    1、Q.分次下载的文件，能确保同一个文件名字，都是同一个文件吗？
       A. 这个由 Qzone 的 API 保证，API 能保证顺序，那么这里就能保证顺序
    2. Q.文件名字非法，不可创建文件，怎么处理？
       A. 会用文件名字 <相册在所有相册中的索引数字>_<文件在相册的索引数字>.jpg 进行二次试创建，
         解决因为相册名字，照片名字引起的文件名非法问题。
    :param arg:
    :return:
    '''
    session, user, album_index, album_name, index, photo = arg

    dest_path = func_save_dir(user)
    fn = u'{0}_{1}_{2}.jpeg'.format(album_name, index, photo.name)
    _func_replace_os_path_sep = lambda x: x.replace(u'/', u'_').replace(u'\\', u'_')
    fn = _func_replace_os_path_sep(fn)
    c_p = os.path.join(dest_path, fn)
    if not io_is_path_valid(c_p):
        c_p = os.path.join(dest_path, u'random_name_{0}_{1}.jpeg'.format(album_index, index))

    # 可能使用其他 api 下载过文件就不再下载
    if os.path.exists(c_p):
        return

    url = photo.url.replace('\\', '')
    attempts = 0
    timeout = 10
    while attempts < 10:
        try:
            req = func_save_photo_net_helper(session, url, timeout)
            break
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            attempts += 1
            timeout += 5
    else:
        io_print(u'down fail user:{0} {1}'.format(user, photo.url))
        return
    c = req.content

    with open(c_p, 'wb') as f:
        f.write(c)


class QzonePhotoManager(object):
    """
    查询QQ空间相册并下载的类。
    """
    albumbase1 = "http://alist.photo.qq.com/fcgi-bin/fcg_list_album?uin={0}&outstyle=2"  # 如果没有设置密保的相册是通过这个地址访问的

    # 2017.02.10 测试: 不对的，已经失效了，效果跟 albumbase1 一样，无法访问密保相册
    # albumbase2 = "http://xalist.photo.qq.com/fcgi-bin/fcg_list_album?uin=" # 设置密保的相册是通过这个地址访问的

    albumbase = albumbase1
    photobase1 = 'http://plist.photo.qq.com/fcgi-bin/fcg_list_photo?uin={0}&albumid={1}&outstyle=json'
    # photobase2 = "http://xaplist.photo.qq.com/fcgi-bin/fcg_list_photo?uin="
    photobase = photobase1

    # v3 的地址都是用过 Chrome 开发者模式查看的
    albumbase_v3 = (
        'https://h5.qzone.qq.com/proxy/domain/tjalist.photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3?'
        'g_tk={gtk}&t={t}&hostUin={dest_user}&uin={user}'
        '&appid=4&inCharset=gbk&outCharset=gbk&source=qzone&plat=qzone&format=jsonp&callbackFun=&mode=2')

    # 不是原图质量
    photobase_v3 = ('https://h5.qzone.qq.com/proxy/domain/tjplist.photo.qzone.qq.com/fcgi-bin/'
                    'cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=5&hostUin={dest_user}'
                    '&topicId={album_id}&noTopic=0&uin={user}&pageStart=0&pageNum=9000'
                    '&inCharset=gbk&outCharset=gbk'
                    '&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1')

    def __init__(self, user, password):
        self.user = user
        self.password = password

        qz = self._login_qzone(user, password)

        self.qzone_g_tk = qz.g_tk()
        self.session = qz.session
        self.cookie = None  # self._get_cookie(qz.session.cookies)

    def _login_qzone(self, user, password):
        qq = qzone.QZone(user, password)

        try:
            qq.login()
        except qqlib.NeedVerifyCode as ex:
            ver = ex.verifier
            ver_path = os.path.join(curpath, 'verify.jpg')
            if os.path.exists(ver_path):
                os.remove(ver_path)
            fimage = ver.fetch_image()
            if not fimage:  # response status code = 500
                raise ex  # rethrow exception
            with open(ver_path, 'wb') as f:
                f.write(fimage)
            io_print(u'验证码保存至{0}'.format(ver_path))
            os.system(ver_path)
            ver_code = io_raw_input(io_out_arg(u'输入验证码:'))
            try:
                ver.verify(ver_code)
            except qqlib.VerifyCodeError:
                io_print(u'验证码错误')
                return self._login_qzone(user, password)
            else:
                qq.login()
        return qq

    def _get_cookie(self, cookies):
        '''
        低版本 API 弃用
        从会话的 cookies 组装为 Qzone 访问所需的 cookie , v3 版本用不到这个
        :param cookies:
        :return:
        '''
        return ('ptisp={0}; RK={1}; ptcz={2};pt2gguin={3}; uin={4}; skey={5}'.format(
            cookies['ptisp'], cookies['RK'], cookies['ptcz'],
            cookies['pt2gguin'], cookies['uin'], cookies['skey']))

    def access_net(self, url, timeout):
        '''
        低版本 API 弃用
        使用组装过的 cookie 访问网络，适用于低版本的 qzone api
        :param url:
        :param timeout:
        :return:
        '''
        import urllib2

        req = urllib2.Request(url)
        req.add_header('Cookie', self.cookie)
        res = urllib2.urlopen(req, timeout=timeout)
        c = res.read().decode('gbk')
        c = c.replace('_Callback(', '')
        c = c.replace(');', '')
        return c

    def get_albums(self, dest_user):
        '''
        低版本 API 弃用
        :param dest_user:
        :return:
        '''
        import json
        ablums = []
        url = self.albumbase.format(dest_user)
        c = self.access_net(url, timeout=8)
        if c:
            c = json.loads(c)
            if 'album' in c:
                for i in c['album']:
                    ablums.append(QzoneAlbum._make([i['id'], i['name'], i['total']]))
        return ablums

    def get_photos_by_album(self, dest_user, album):
        '''
        低版本 API 弃用
        :param dest_user:
        :param album:
        :return:
        '''
        import json
        photos = []
        url = self.photobase.format(dest_user, album.uid)
        c = self.access_net(url, timeout=10)
        if c:
            c = json.loads(c)
            if 'pic' in c:
                for i in c['pic']:
                    photos.append(QzonePhoto._make([
                        i['url'], i['name'], album
                    ]))
        return photos

    def get_photos(self, dest_user):
        '''
        低版本 API 弃用 , 不再维护，可能有 bug
        :param dest_user:
        :return:
        '''
        from concurrent.futures import ThreadPoolExecutor

        albums = self.get_albums(dest_user)
        for i, album in enumerate(albums):
            if album.count:
                photos = self.get_photos_by_album(dest_user, album)
                photos = [(None, dest_user, album.name, i, photo) for i, photo in enumerate(photos)]

    def access_net_v3(self, url, timeout):
        '''
        使用登录时的 session，cookie 访问网络 ，适用于高版本的 qzone api
        :param url:
        :param timeout:
        :return:
        '''
        r = self.session.get(url, timeout=timeout)
        c = r.text
        c = c.replace('_Callback(', '')
        c = c.replace(');', '')
        return c

    def get_albums_v3(self, dest_user):
        import json
        ablums = []
        url = self.albumbase_v3.format(gtk=self.qzone_g_tk,
                                       t=random.Random().random(),
                                       dest_user=dest_user,
                                       user=self.user)

        c = self.access_net_v3(url, timeout=8)
        if c:
            c = json.loads(c)
            if 'data' in c and 'albumList' in c['data']:
                for i in c['data']['albumList']:
                    ablums.append(QzoneAlbum._make([i['id'], i['name'], i['total']]))
        return ablums

    def get_photos_by_album_v3(self, dest_user, album):
        import json

        photos = []
        url = self.photobase_v3.format(
            gtk=self.qzone_g_tk,
            t=random.Random().random(),
            dest_user=dest_user,
            user=self.user,
            album_id=album.uid)

        c = self.access_net_v3(url, timeout=10)
        if c:
            c = json.loads(c)
            if 'data' in c and 'photoList' in c['data']:
                photolist = c['data']['photoList']

                # 先看是否存在原图
                # get picKey(=lloc)
                if photolist and 'lloc' in photolist[0]:
                    p = self.get_raw_photos_by_album(dest_user, album, photolist[0]['lloc'])
                    if p:
                        return p
                for i in photolist:
                    pic_url = ('origin_url' in i and i['origin_url'] or i['url'])
                    photos.append(QzonePhoto._make([
                        pic_url, i['name'], album
                    ]))
        return photos

    def get_raw_photos_by_album(self, dest_user, album, pic_key):
        import json

        url_raw_photo_base = ('https://h5.qzone.qq.com/proxy/domain/tjplist.photo.qq.com/fcgi-bin/'
                              'cgi_floatview_photo_list_v2?'
                              'g_tk={gtk}&t={t}&topicId={album_id}&picKey={pic_key}'
                              '&shootTime=&cmtOrder=1&fupdate=1&plat=qzone&source=qzone'
                              '&cmtNum=10&inCharset=utf-8&outCharset=utf-8'
                              '&offset=0&uin={user}&appid=4&isFirst=1&hostUin={dest_user}&postNum=9999')

        photos = []
        url = url_raw_photo_base.format(
            gtk=self.qzone_g_tk,
            t=random.Random().random(),
            dest_user=dest_user,
            user=self.user,
            album_id=album.uid,
            pic_key=pic_key)

        c = self.access_net_v3(url, timeout=10)
        if c:
            c = json.loads(c)
            if 'data' in c and 'photos' in c['data']:
                for i in c['data']['photos']:
                    pic_url = ('raw' in i and i['raw']
                               or 'origin' in i and i['origin']
                               or i['url'])
                    photos.append(QzonePhoto._make([
                        pic_url, i['name'], album
                    ]))
        return photos

    def get_photos_v3(self, dest_user):
        '''
        能访问所有相册, 前提是先有权限访问该相册
        :param dest_user:
        :return:
        '''
        from concurrent.futures import ThreadPoolExecutor

        # 先获得所有相册
        albums = self.get_albums_v3(dest_user)
        photos_all = []
        io_print(u'获取到 {0} 个相册'.format(len(albums)))
        for i, album in enumerate(albums):
            if album.count:
                # 根据相册 id 获取相册内所有照片
                photos = self.get_photos_by_album_v3(dest_user, album)
                photos = [(self.session, dest_user, i, album.name, si, photo) for si, photo in enumerate(photos)]

                p = func_save_dir(dest_user)

                if not os.path.exists(p):
                    os.makedirs(p)
                photos_all.extend(photos)

        with ThreadPoolExecutor(max_workers=20) as pool:
            r = pool.map(func_save_photo, photos_all)
            list(r)

        if not albums:
            io_stderr_print(u'未找到 {0} 可下载的相册'.format(dest_user))


def entry():
    # 你的 QQ
    main_user = ""
    main_pass = ""

    # 要处理的目标 QQ 号
    dest_users = [""]

    a = QzonePhotoManager(main_user, main_pass)
    io_print(u'登录成功')

    # 如果遇到下载失败的，产生超时异常终止程序运行的，可以再重新运行，已经下载过的文件不会重新下载
    for e in dest_users:
        io_print(u'正在处理用户 {0}'.format(e))
        a.get_photos_v3(e)
        io_print(u'处理完成')


if __name__ == '__main__':
    entry()
