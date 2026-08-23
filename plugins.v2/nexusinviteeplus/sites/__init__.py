"""
NexusPHP站点邀请系统解析器基类
"""
import re
from abc import ABCMeta, abstractmethod
from typing import Dict, Optional, Any

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from app.log import logger


class _ISiteHandler(metaclass=ABCMeta):
    """
    站点邀请系统处理的基类，所有站点处理类都需要继承此类
    """
    # 站点类型标识
    site_schema = ""
    
    @classmethod
    @abstractmethod
    def match(cls, site_url: str) -> bool:
        """
        判断是否匹配该站点处理类
        :param site_url: 站点URL
        :return: 是否匹配
        """
        pass
    
    @abstractmethod
    def parse_invite_page(self, site_info: Dict[str, Any], session: requests.Session) -> Dict[str, Any]:
        """
        解析站点邀请页面
        :param site_info: 站点信息
        :param session: 已配置好的请求会话
        :return: 解析结果
        """
        pass

    # 按顺序试这几个入口找用户ID。首页排在最前面：像葡萄(pt.sjtu.edu.cn)
    # 这类站点的 usercp.php 挂着二次验证会跳登录页，只认 usercp.php 的话
    # 明明登录着也会被判成 Cookie 失效。
    _USER_ID_PAGES = ("index.php", "usercp.php", "/")

    @staticmethod
    def _extract_user_id(html: str) -> Optional[str]:
        """从一页 HTML 里找当前用户的 id。"""
        soup = BeautifulSoup(html, 'html.parser')

        # 个人资料链接最直接
        for link in soup.select('a[href*="userdetails.php"]'):
            m = re.search(r'[?&]id=(\d+)(?![\da-zA-Z-])', link.get('href', ''))
            if m:
                return m.group(1)

        # 其次是带 id 的邀请页链接
        for link in soup.select('a[href*="invite.php"]'):
            m = re.search(r'[?&]id=(\d+)(?![\da-zA-Z-])', link.get('href', ''))
            if m:
                return m.group(1)

        # 有些魔改皮肤把用户ID塞在 JS 变量或 data 属性里
        m = re.search(r'userdetails\.php\?id=(\d+)', html)
        return m.group(1) if m else None

    @staticmethod
    def _get_user_id(session: requests.Session, site_url: str) -> Optional[str]:
        """
        获取用户ID

        逐个入口试，任何一个页面能解析出来就算成功；全都失败才返回 None。
        :param session: 请求会话
        :param site_url: 站点URL
        :return: 用户ID
        """
        for page in _ISiteHandler._USER_ID_PAGES:
            try:
                response = session.get(urljoin(site_url, page.lstrip("/")), timeout=(10, 25))
                if response.status_code >= 400:
                    continue
                user_id = _ISiteHandler._extract_user_id(response.text or "")
                if user_id:
                    return user_id
            except Exception as e:
                logger.debug(f"从 {page} 获取用户ID失败: {str(e)}")
                continue

        logger.error(f"获取用户ID失败: {site_url} 的 {'/'.join(_ISiteHandler._USER_ID_PAGES)} 都没解析出用户ID")
        return None

    # NexusPHP 系站点统一在用户名后面挂一个 <img class="disabled" alt="Disabled">
    # 来标记被封禁的用户，页面上并没有单独的「启用」列可看。
    _BANNED_SELECTOR = ('img.disabled, img[alt="Disabled"], img[alt="disabled"], '
                        'img[src*="disabled"], s, strike, del')
    _BANNED_ROW_CLASSES = ("rowbanned", "banned", "disabled")

    @classmethod
    def _is_banned_row(cls, node) -> bool:
        """判断一行（或一个用户名单元格）对应的用户是不是被封禁了。"""
        if node is None:
            return False
        classes = node.get("class") or []
        if any(c in cls._BANNED_ROW_CLASSES for c in classes):
            return True
        return node.select_one(cls._BANNED_SELECTOR) is not None

    @staticmethod
    def _convert_size_to_bytes(size_str: str) -> float:
        """
        将大小字符串转换为字节数
        :param size_str: 大小字符串
        :return: 字节数
        """
        if not size_str or size_str.strip() == '':
            logger.warning(f"空的大小字符串")
            return 0

        # 处理特殊情况
        if size_str.lower() == 'inf.' or size_str.lower() == 'inf' or size_str == '∞':
            logger.info(f"识别到无限大值: {size_str}")
            return 1e20  # 使用一个非常大的数值代替无穷大

        try:
            # 标准化字符串，替换逗号为点
            size_str = size_str.replace(',', '.')

            # 分离数字和单位
            # 正则表达式匹配数字部分和单位部分
            matches = re.match(
                r'([\d.]+)\s*([KMGTPEZY]?i?B)', size_str, re.IGNORECASE)

            if not matches:
                # 尝试匹配仅有数字的情况
                try:
                    return float(size_str)
                except ValueError:
                    logger.warning(f"无法解析大小字符串: {size_str}")
                    return 0

            size_num, unit = matches.groups()

            # 尝试转换数字
            try:
                size_value = float(size_num)
            except ValueError:
                logger.warning(f"无法转换大小值为浮点数: {size_num}")
                return 0

            # 单位转换
            unit = unit.upper()

            units = {
                'B': 1,
                'KB': 1024,
                'KIB': 1024,
                'MB': 1024 ** 2,
                'MIB': 1024 ** 2,
                'GB': 1024 ** 3,
                'GIB': 1024 ** 3,
                'TB': 1024 ** 4,
                'TIB': 1024 ** 4,
                'PB': 1024 ** 5,
                'PIB': 1024 ** 5,
                'EB': 1024 ** 6,
                'EIB': 1024 ** 6,
                'ZB': 1024 ** 7,
                'ZIB': 1024 ** 7,
                'YB': 1024 ** 8,
                'YIB': 1024 ** 8
            }

            # 处理简写单位
            if unit in ['K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']:
                unit = unit + 'B'

            if unit not in units:
                logger.warning(f"未知的大小单位: {unit}")
                return size_value  # 假设是字节

            return size_value * units[unit]

        except Exception as e:
            logger.warning(f"转换大小字符串到字节时出错 '{size_str}': {str(e)}")
            return 0

    @staticmethod
    def _calculate_ratio(uploaded: str, downloaded: str) -> str:
        """
        计算分享率
        :param uploaded: 上传量
        :param downloaded: 下载量
        :return: 分享率字符串
        """
        try:
            up_bytes = _ISiteHandler._convert_size_to_bytes(uploaded)
            down_bytes = _ISiteHandler._convert_size_to_bytes(downloaded)
            
            if down_bytes == 0:
                return "∞" if up_bytes > 0 else "0"
            
            ratio = up_bytes / down_bytes
            return f"{ratio:.3f}"
        except Exception as e:
            logger.error(f"计算分享率失败: {str(e)}")
            return "0" 