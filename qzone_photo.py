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
'''

# ------------------------------------------------------------------------------
# feedback :
# CHANGELOG:
# 2017-02-10 v1.00 fooofei: first version

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


def func_save_photo(arg):
    '''
    线程函数，运行在线程池中
    文件保存格式 <相册名字>_<文件在相册>_<文件名字>.jpeg
    :param arg:
    :return:
    '''
    session, user, album_name, index, photo = arg

    dest_path = func_save_dir(user)
    c_p = os.path.join(dest_path, u'{0}_{1}_{2}.jpeg'.format(album_name, index, photo.name))

    # 可能使用其他 api 下载过文件就不再下载
    if os.path.exists(c_p):
        return

    url = photo.url.replace('\\', '')
    attempts = 0
    timeout = 10
    while attempts < 3:
        try:
            if session:  # 使用已经登陆过的账户下载，不然加密的照片下载都是写着“加密照片”
                req = session.post(url, timeout=timeout)
            else:
                req = requests.post(url, timeout=timeout)
            break
        except requests.ReadTimeout:
            attempts += 1
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
        'http://h5.qzone.qq.com/proxy/domain/tjalist.photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3?'
        'g_tk={gtk}&t={t}&hostUin={dest_user}&uin={user}'
        '&appid=4&inCharset=gbk&outCharset=gbk&source=qzone&plat=qzone&format=jsonp&callbackFun=')

    photobase_v3 = ('http://h5.qzone.qq.com/proxy/domain/tjplist.photo.qzone.qq.com/fcgi-bin/'
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
        self.cookie = self._get_cookie(qz.session.cookies)

    def _login_qzone(self, user, password):
        qq = qzone.QZone(user, password)

        try:
            qq.login()
        except qqlib.NeedVerifyCode as ex:
            ver = ex.verifier
            ver_path = os.path.join(curpath, 'verify.jpg')
            if os.path.exists(ver_path):
                os.remove(ver_path)
            with open(ver_path, 'wb') as f:
                f.write(ver.image)
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
        从会话的 cookies 组装为 Qzone 访问所需的 cookie , v3 版本用不到这个
        :param cookies:
        :return:
        '''
        return ('ptisp={0}; RK={1}; ptcz={2};pt2gguin={3}; uin={4}; skey={5}'.format(
            cookies['ptisp'], cookies['RK'], cookies['ptcz'],
            cookies['pt2gguin'], cookies['uin'], cookies['skey']))

    def access_net(self, url, timeout):
        '''
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
        import json
        ablums = []
        url = self.albumbase.format(dest_user)
        c = self.access_net(url, timeout=8)
        c = json.loads(c)
        if 'album' in c:
            for i in c['album']:
                ablums.append(QzoneAlbum._make([i['id'], i['name'], i['total']]))
        return ablums

    def get_photos_by_album(self, dest_user, album):
        import json
        photos = []
        url = self.photobase.format(dest_user, album.uid)
        c = self.access_net(url, timeout=10)
        c = json.loads(c)
        if 'pic' in c:
            for i in c['pic']:
                photos.append(QzonePhoto._make([
                    i['url'], i['name'], album
                ]))
        return photos

    def get_photos(self, dest_user):
        from concurrent.futures import ThreadPoolExecutor

        albums = self.get_albums(dest_user)
        for i, album in enumerate(albums):
            if album.count:
                photos = self.get_photos_by_album(dest_user, album)
                photos = [(self.session, dest_user, album.name, i, photo) for i, photo in enumerate(photos)]

                p = func_save_dir(dest_user)
                if not os.path.exists(p):
                    os.makedirs(p)

                with ThreadPoolExecutor(max_workers=4) as pool:
                    r = pool.map(func_save_photo, photos)
                    list(r)

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
        if c :
            c = json.loads(c)
            if 'data' in c and 'albumListModeSort' in c['data']:
                for i in c['data']['albumListModeSort']:
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
        if c :
            c = json.loads(c)
            if 'data' in c and 'photoList' in c['data']:
                for i in c['data']['photoList']:
                    photos.append(QzonePhoto._make([
                        i['url'], i['name'], album
                    ]))
        return photos

    def get_photos_v3(self, dest_user):
        '''
        能访问所有相册, 前提是先有权限访问该相册
        :param dest_user:
        :return:
        '''
        from concurrent.futures import ThreadPoolExecutor

        albums = self.get_albums_v3(dest_user)
        for i, album in enumerate(albums):
            if album.count:
                photos = self.get_photos_by_album_v3(dest_user, album)
                photos = [(self.session, dest_user, album.name, i, photo) for i, photo in enumerate(photos)]

                p = func_save_dir(dest_user)
                if not os.path.exists(p):
                    os.makedirs(p)

                with ThreadPoolExecutor(max_workers=4) as pool:
                    r = pool.map(func_save_photo, photos)
                    list(r)


def entry():
    # 你的 QQ
    main_user = ''
    main_pass = ''

    # 要处理的目标 QQ 号
    dest_users = ['']

    #
    # 低版本 API 下载公开相册，高版本 API 下载加密相册
    # 测试结果显示 高版本 API 无法下载公开相册

    a = QzonePhotoManager(main_user, main_pass)
    io_print(u'登录成功')

    for e in dest_users:
        io_print(u'正在处理用户 {0}'.format(e))
        io_print(u'使用低版本 API 下载公开相册')
        a.get_photos(e)
        io_print(u'使用高版本 API 下载加密相册')
        a.get_photos_v3(e)
        io_print(u'处理完成')


if __name__ == '__main__':
    entry()
