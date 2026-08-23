"""
憨憨站点处理
"""
import re
import json
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.log import logger
from app.db.site_oper import SiteOper
from . import _ISiteHandler


class HHClubHandler(_ISiteHandler):
    """
    憨憨站点处理类
    """
    # 站点类型标识
    site_schema = "hhclub"
    
    @classmethod
    def match(cls, site_url: str) -> bool:
        """
        判断是否匹配憨憨站点
        :param site_url: 站点URL
        :return: 是否匹配
        """
        # 憨憨站点的特征 - 域名中包含 hhanclub 或者 hhclub
        hhclub_features = [
            "hhanclub",   # 憨憨官方域名
            "hhclub",      # 可能的简写域名
            "hhan"   # 憨憨官方域名
        ]
        
        site_url_lower = site_url.lower()
        for feature in hhclub_features:
            if feature in site_url_lower:
                logger.info(f"匹配到憨憨站点特征: {feature}")
                return True
        
        return False
    
    def parse_invite_page(self, site_info: Dict[str, Any], session: requests.Session) -> Dict[str, Any]:
        """
        解析憨憨站点邀请页面
        :param site_info: 站点信息
        :param session: 已配置好的请求会话
        :return: 解析结果
        """
        site_name = site_info.get("name", "")
        site_url = site_info.get("url", "")
        site_id = site_info.get("id")
        
        logger.info(f"开始解析站点 {site_name} 邀请页面，站点ID: {site_id}, URL: {site_url}")
        
        result = {
            "invite_status": {
                "can_invite": False,
                "reason": "",
                "permanent_count": 0,
                "temporary_count": 0,
                "bonus": 0,  # 魔力值
                "permanent_invite_price": 0,  # 永久邀请价格
                "temporary_invite_price": 0   # 临时邀请价格
            },
            "invitees": []
        }
        
        try:
            # 获取用户ID
            user_id = self._get_user_id(session, site_url)
            if not user_id:
                logger.error(f"站点 {site_name} 无法获取用户ID")
                result["invite_status"]["reason"] = "无法获取用户ID，请检查站点Cookie是否有效"
                return result
            
            # --- 获取邀请数量和权限 ---
            try:
                index_url = urljoin(site_url, "index.php")
                logger.info(f"站点 {site_name} 正在从主页获取邀请数量: {index_url}")
                index_response = session.get(index_url, timeout=(10, 30))
                index_response.raise_for_status()
                invite_counts = self._parse_hhclub_homepage(site_name, index_response.text)
                result["invite_status"]["permanent_count"] = invite_counts["permanent_count"]
                result["invite_status"]["temporary_count"] = 0 # 憨憨无临时
                logger.info(f"站点 {site_name} 从主页获取到邀请数量: 永久={invite_counts['permanent_count']}, 临时=0")
            except Exception as e:
                logger.error(f"站点 {site_name} 从主页获取邀请数量失败: {str(e)}")

            try:
                invite_url = urljoin(site_url, f"invite.php?id={user_id}")
                response = session.get(invite_url, timeout=(10, 30))
                response.raise_for_status()
                invite_button_info = self._check_hhclub_invite_permission(site_name, response.text)
                result["invite_status"]["can_invite"] = invite_button_info["can_invite"]
                if result["invite_status"]["can_invite"]:
                    if result["invite_status"]["permanent_count"] > 0:
                        result["invite_status"]["reason"] = f"可用邀请数: 永久={result['invite_status']['permanent_count']}"
                    else:
                        result["invite_status"]["reason"] = "可以邀请其他人" # 或者基于按钮文本判断
                else:
                    result["invite_status"]["reason"] = invite_button_info["reason"]
            except Exception as e:
                 logger.error(f"站点 {site_name} 获取或检查邀请权限页面失败: {str(e)}")
                 result["invite_status"]["reason"] = f"检查邀请权限失败: {str(e)}"
            # --- 邀请数量和权限获取结束 ---

            # --- 解析后宫列表，包含翻页和防重逻辑 ---
            logger.info(f"站点 {site_name} 开始获取后宫列表...")
            invitee_url = urljoin(site_url, f"invite.php?id={user_id}&menu=invitee")
            first_page_response = session.get(invitee_url, timeout=(10, 30))
            first_page_response.raise_for_status()

            first_page_result = self._parse_hhclub_invitee_page(site_name, site_url, first_page_response.text)
            result["invitees"] = first_page_result["invitees"]

            previous_page_invitee_ids = set()
            if result["invitees"]:
                first_page_invitee_ids = {invitee.get('profile_url') or invitee.get('username') for invitee in result["invitees"]}
                previous_page_invitee_ids = first_page_invitee_ids
                logger.debug(f"站点 {site_name} 首页收集到 {len(previous_page_invitee_ids)} 个后宫ID用于重复检测")

            if len(result["invitees"]) >= 50:
                logger.info(f"站点 {site_name} 首页后宫成员数量达到50人，尝试获取后续页面...")
                next_page = 1
                max_pages = 100

                while next_page < max_pages:
                    next_page_url = urljoin(site_url, f"invite.php?id={user_id}&menu=invitee&page={next_page}")
                    logger.info(f"站点 {site_name} 正在获取第 {next_page+1} 页后宫成员数据: {next_page_url}")

                    try:
                        next_response = session.get(next_page_url, timeout=(10, 30))
                        next_response.raise_for_status()
                        next_page_result = self._parse_hhclub_invitee_page(site_name, site_url, next_response.text)

                        if not next_page_result["invitees"]:
                            logger.info(f"站点 {site_name} 第 {next_page+1} 页没有后宫成员数据，停止获取")
                            break

                        current_page_invitee_ids = {invitee.get('profile_url') or invitee.get('username') for invitee in next_page_result["invitees"]}

                        if previous_page_invitee_ids and current_page_invitee_ids == previous_page_invitee_ids:
                            logger.warning(f"站点 {site_name} 检测到第 {next_page+1} 页内容与上一页重复，停止翻页")
                            break

                        result["invitees"].extend(next_page_result["invitees"])
                        logger.info(f"站点 {site_name} 第 {next_page+1} 页解析到 {len(next_page_result['invitees'])} 个后宫成员")

                        previous_page_invitee_ids = current_page_invitee_ids

                        if len(next_page_result["invitees"]) < 50:
                            logger.info(f"站点 {site_name} 第 {next_page+1} 页后宫成员数量少于50人({len(next_page_result['invitees'])}人)，停止获取")
                            break

                        next_page += 1

                    except Exception as e:
                        logger.warning(f"站点 {site_name} 获取第 {next_page+1} 页数据失败: {str(e)}")
                        break
            else:
                logger.info(f"站点 {site_name} 首页后宫成员数量少于50人({len(result['invitees'])}人)，不再查找后续页面")
            # --- 后宫列表解析结束 ---

            # --- 获取魔力值和邀请价格 ---
            try:
                bonus_url = urljoin(site_url, "mybonus.php")
                bonus_response = session.get(bonus_url, timeout=(10, 30))
                if bonus_response.status_code == 200:
                    bonus_data = self._parse_hhclub_bonus_shop(site_name, bonus_response.text)
                    result["invite_status"]["bonus"] = bonus_data["bonus"]
                    result["invite_status"]["permanent_invite_price"] = bonus_data["permanent_invite_price"]
                    result["invite_status"]["temporary_invite_price"] = 0

                    if result["invite_status"]["bonus"] > 0 and result["invite_status"]["permanent_invite_price"] > 0:
                        can_buy_permanent = int(result["invite_status"]["bonus"] / result["invite_status"]["permanent_invite_price"])
                        if result["invite_status"]["reason"] and not result["invite_status"]["can_invite"]:
                            if can_buy_permanent > 0:
                                result["invite_status"]["reason"] += f"，但您的憨豆({result['invite_status']['bonus']})可购买永久邀请({can_buy_permanent}个,{result['invite_status']['permanent_invite_price']}憨豆/个)"
                                if result["invite_status"]["permanent_count"] == 0:
                                    result["invite_status"]["can_invite"] = True
                        elif result["invite_status"]["reason"]:
                            if can_buy_permanent > 0:
                                result["invite_status"]["reason"] += f"，憨豆({result['invite_status']['bonus']})还可购买永久邀请({can_buy_permanent}个,{result['invite_status']['permanent_invite_price']}憨豆/个)"
            except Exception as e:
                logger.warning(f"站点 {site_name} 解析魔力值商店失败: {str(e)}")
            # --- 魔力值解析结束 ---

            if result["invitees"]:
                 logger.info(f"站点 {site_name} 共解析到 {len(result['invitees'])} 个后宫成员")

            return result

        except Exception as e:
            logger.error(f"解析站点 {site_name} 邀请页面时发生严重错误: {str(e)}")
            result["invite_status"]["reason"] = f"解析邀请页面失败: {str(e)}"
            return result
    
    def _parse_hhclub_userdetails_page(self, site_name: str, site_url: str, html_content: str) -> Dict[str, Any]:
        """
        解析憨憨站点用户详情页，获取邀请数量
        :param site_name: 站点名称
        :param site_url: 站点URL
        :param html_content: HTML内容
        :return: 邀请数量
        """
        result = {
            "permanent_count": 0,
            "temporary_count": 0
        }
        
        try:
            # 初始化BeautifulSoup对象
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 方法1: 查找包含"邀请"的行（原有逻辑）
            invite_row = soup.select_one('td.rowhead:-soup-contains("邀请") + td.rowfollow')
            
            if invite_row:
                # 获取邀请文本
                invite_text = invite_row.get_text(strip=True)
                
                # 通过正则表达式提取邀请数量
                invite_match = re.search(r'(\d+)', invite_text)
                
                if invite_match:
                    permanent_count = invite_match.group(1)
                    
                    try:
                        result["permanent_count"] = int(permanent_count)
                        logger.info(f"站点 {site_name} 从用户详情页解析到邀请数量: 永久={result['permanent_count']}")
                    except (ValueError, TypeError):
                        logger.warning(f"站点 {site_name} 无法将邀请数量转换为整数: {permanent_count}")
                else:
                    logger.warning(f"站点 {site_name} 未找到邀请数量: {invite_text}")
            
            # 方法2: 尝试从用户弹出面板中查找邀请数量
            if result["permanent_count"] == 0:
                logger.info(f"站点 {site_name} 尝试从用户弹出面板获取邀请数量")
                
                # 查找包含"邀请"的元素，特别是在用户信息弹出面板中
                invite_elements = soup.select('.flex.flex-row.items-center')
                for elem in invite_elements:
                    # 检查该元素是否包含图片和邀请链接
                    img = elem.select_one('img[alt="邀请"]')
                    if img:
                        # 找到包含邀请数量的div
                        invite_div = elem.select_one('a > div.text-sm.flex.flex-wrap.break-all')
                        if invite_div:
                            invite_text = invite_div.get_text(strip=True)
                            # 通过正则表达式提取邀请数量
                            invite_match = re.search(r'\[邀请\]:\s*(\d+)', invite_text)
                            if invite_match:
                                try:
                                    result["permanent_count"] = int(invite_match.group(1))
                                    logger.info(f"站点 {site_name} 从用户弹出面板解析到邀请数量: 永久={result['permanent_count']}")
                                except (ValueError, TypeError):
                                    logger.warning(f"站点 {site_name} 无法将弹出面板中的邀请数量转换为整数: {invite_match.group(1)}")
                            else:
                                logger.warning(f"站点 {site_name} 未找到弹出面板中的邀请数量: {invite_text}")
            
            # 方法3: 如果方法1和方法2都失败，尝试更通用的方法
            if result["permanent_count"] == 0:
                # 尝试找到所有包含"邀请"的元素
                invite_texts = []
                for elem in soup.find_all(string=lambda text: "邀请" in str(text) if text else False):
                    parent = elem.parent
                    if parent:
                        invite_texts.append(parent.get_text(strip=True))
                
                for text in invite_texts:
                    invite_match = re.search(r'[邀请].*?(\d+)', text)
                    if invite_match:
                        try:
                            result["permanent_count"] = int(invite_match.group(1))
                            logger.info(f"站点 {site_name} 通过通用方法解析到邀请数量: 永久={result['permanent_count']}")
                            break
                        except (ValueError, TypeError):
                            continue
                
                if result["permanent_count"] == 0:
                    logger.warning(f"站点 {site_name} 所有方法均未找到邀请数量")
                    
        except Exception as e:
            logger.error(f"站点 {site_name} 解析用户详情页邀请数量失败: {str(e)}")
        
        return result
    
    def _check_hhclub_invite_permission(self, site_name: str, html_content: str) -> Dict[str, Any]:
        """
        检查憨憨站点邀请权限
        :param site_name: 站点名称
        :param html_content: HTML内容
        :return: 邀请权限
        """
        result = {
            "can_invite": False,
            "reason": ""
        }
        
        try:
            # 初始化BeautifulSoup对象
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 首先检查是否有"对不起"消息 - 如果有，一定是不可邀请
            # 尝试多种可能的选择器来匹配"对不起"消息
            sorry_divs = [
                soup.select_one('.bg-\\[\\#F29D38\\]:-soup-contains("对不起")'),  # 原选择器
                soup.select_one('div.bg-\\[\\#F29D38\\]:-soup-contains("对不起")'),
                soup.select_one('div:-soup-contains("对不起")')  # 更通用的选择器
            ]
            
            sorry_div = next((div for div in sorry_divs if div is not None), None)
            if sorry_div:
                # 找到提示信息 - 尝试多种可能的选择器
                info_divs = [
                    soup.select_one('.bg-\\[\\#FFFFFF\\]'),  # 原选择器
                    soup.select_one('div.bg-\\[\\#FFFFFF\\]'),
                    soup.select_one('div.tips div.bg-\\[\\#FFFFFF\\]'),
                    sorry_div.find_next('div')  # 在"对不起"之后的第一个div
                ]
                
                info_div = next((div for div in info_divs if div is not None), None)
                if info_div:
                    reason_text = info_div.get_text(strip=True)
                    result["can_invite"] = False
                    result["reason"] = reason_text
                    logger.info(f"站点 {site_name} 不可邀请，原因: {reason_text}")
                    return result
                else:
                    # 如果找到了"对不起"但找不到具体原因，返回通用原因
                    result["can_invite"] = False
                    result["reason"] = "该账号暂无邀请权限"
                    logger.info(f"站点 {site_name} 不可邀请，无法获取具体原因，但检测到'对不起'提示")
                    return result
            
            # 如果没有"对不起"消息，尝试直接查找包含权限限制的内容
            perm_div = soup.find(string=re.compile(r'只有.*及以上的用户才能发送邀请'))
            if perm_div:
                parent_div = perm_div.parent
                if parent_div:
                    reason_text = parent_div.get_text(strip=True)
                    result["can_invite"] = False
                    result["reason"] = reason_text
                    logger.info(f"站点 {site_name} 不可邀请，原因: {reason_text}")
                    return result
            
            # 检查邀请按钮
            invite_button = soup.select_one('input[type="submit"][value*="邀请"]')
            if invite_button:
                button_value = invite_button.get('value', '')
                
                # 检查按钮文本是否包含权限限制信息
                if any(phrase in button_value for phrase in ['才可以发送邀请', '才能发送邀请', '等级才可', '及以上']):
                    result["can_invite"] = False
                    result["reason"] = button_value
                    logger.info(f"站点 {site_name} 不可邀请，权限不足: {button_value}")
                    return result
                
                # 如果按钮存在且没有禁用，且没有权限限制
                if not invite_button.get('disabled'):
                    result["can_invite"] = True
                    result["reason"] = "可以邀请其他人"
                    logger.info(f"站点 {site_name} 可以邀请，按钮文本: {button_value}")
                else:
                    # 如果按钮被禁用，获取原因
                    result["can_invite"] = False
                    result["reason"] = button_value
                    logger.info(f"站点 {site_name} 不可邀请，按钮被禁用: {button_value}")
            else:
                # 尝试查找隐藏的按钮
                hidden_button = soup.select_one('input[type="submit"][value*="邀请"].hidden')
                if hidden_button:
                    button_value = hidden_button.get('value', '')
                    result["can_invite"] = False
                    result["reason"] = button_value
                    logger.info(f"站点 {site_name} 不可邀请，按钮被隐藏: {button_value}")
                else:
                    # 查找是否有权限限制的文本
                    level_restrictions = [
                        soup.find(string=re.compile(r'维护开发员.*及以上')),
                        soup.find(string=re.compile(r'等级才可以')),
                        soup.find(string=re.compile(r'才能发送邀请'))
                    ]
                    
                    level_restriction = next((text for text in level_restrictions if text), None)
                    if level_restriction:
                        result["can_invite"] = False
                        parent_elem = level_restriction.parent
                        reason = level_restriction.strip() if parent_elem is None else parent_elem.get_text(strip=True)
                        result["reason"] = reason
                        logger.info(f"站点 {site_name} 不可邀请，权限不足: {reason}")
                    else:
                        # 找不到特定提示，通用提示
                        result["can_invite"] = False
                        result["reason"] = "无法找到邀请按钮，请检查站点是否已登录"
                        logger.warning(f"站点 {site_name} 未找到邀请按钮")
        except Exception as e:
            logger.error(f"站点 {site_name} 检查邀请权限失败: {str(e)}")
            result["reason"] = f"检查邀请权限失败: {str(e)}"
        
        return result
    
    # 憨憨用的是 tailwind grid 而不是 table，表头行和数据行共用同一个
    # grid-cols-[...] 类名——靠这个类把它们串起来是最稳的锚点。
    @staticmethod
    def _find_invitee_grid(soup):
        """在页面里定位后宫表的表头行和全部数据行。"""
        header = None
        for div in soup.select('div[class*="grid-cols-"]'):
            text = div.get_text(" ", strip=True)
            if "用户名" in text and "分享率" in text:
                header = div
                break
        if header is None:
            return None, []

        grid_classes = [c for c in (header.get("class") or []) if c.startswith("grid-cols-")]
        if not grid_classes:
            return header, []

        rows = [d for d in soup.select("div")
                if d is not header and any(c in (d.get("class") or []) for c in grid_classes)]
        return header, rows

    # 状态列的取值，用来在一行里认出哪一格是状态
    _STATUS_WORDS = ("已确认", "待确认", "未确认", "已禁用", "封禁", "禁用", "已封禁")

    def _parse_hhclub_invitee_page(self, site_name: str, site_url: str, html_content: str) -> Dict[str, Any]:
        """
        解析憨憨站点后宫成员页面HTML内容

        原来这里是按表头文字逐列匹配的，有两个问题：一是选表头时用
        div[class*="grid-cols-"][class*="bg-"]，第一个命中的是左侧导航菜单
        （bg-white grid grid-cols-1），子元素为空，于是一路报「表头行为空」
        直接返回 0 人；二是就算选对了表头，它的子格只有 11 个而数据行有 12 个
        （表头漏了「后宫加成」这一格），按下标对齐从第 9 列起就全串位了。
        所以这里改成认最左边几列的固定顺序，状态列按内容找。

        :param site_name: 站点名称
        :param site_url: 站点URL
        :param html_content: HTML内容
        :return: 解析结果
        """
        result = {
            "invitees": []
        }

        soup = BeautifulSoup(html_content, 'html.parser')

        if soup.select_one('div:-soup-contains("没有被邀者")'):
            logger.info(f"站点 {site_name} 没有后宫成员")
            return result

        header, data_rows = self._find_invitee_grid(soup)
        if header is None:
            logger.warning(f"站点 {site_name} 页面里没找到后宫表（可能站点改版了）")
            return result
        if not data_rows:
            logger.info(f"站点 {site_name} 后宫表里只有表头，没有成员")
            return result

        for row in data_rows:
            cells = row.select(':scope > div')
            if len(cells) < 5:
                continue

            texts = [c.get_text(strip=True) for c in cells]
            username_link = cells[0].select_one('a')
            username = (username_link.get_text(strip=True) if username_link else texts[0]).strip()
            if not username:
                continue

            status = ""
            for text in texts:
                if text in self._STATUS_WORDS:
                    status = text
                    break

            # 憨憨的「状态」列对所有人都写「已确认」，被封禁与否是靠用户名后面
            # 那个 <img class="disabled" alt="Disabled"> 标出来的，只看状态列会漏掉。
            banned = self._is_banned_row(cells[0]) or self._is_banned_row(row)
            if not banned and status:
                banned = status not in ("已确认", "待确认", "未确认")
            if banned and status in ("", "已确认"):
                status = "已禁用"

            invitee = {
                "username": username,
                "email": texts[1],
                "uploaded": texts[2],
                "downloaded": texts[3],
                "ratio": texts[4],
                "enabled": "No" if banned else "Yes",
                "status": status or "已确认",
            }
            if len(texts) > 5:
                invitee["seeding"] = texts[5]
            if username_link and username_link.get("href"):
                invitee["profile_url"] = urljoin(site_url, username_link["href"])

            # ratio_health / ratio_label 交给 parsing.sanitize_invitees 统一算，
            # 免得这里和总览页各算一套对不上
            result["invitees"].append(invitee)

        logger.info(f"站点 {site_name} 解析到 {len(result['invitees'])} 个后宫成员")
        return result
    
    def _parse_hhclub_bonus_shop(self, site_name: str, html_content: str) -> Dict[str, Any]:
        """
        解析憨憨站点魔力值商店页面
        :param site_name: 站点名称
        :param html_content: HTML内容
        :return: 魔力值和邀请价格信息
        """
        result = {
            "bonus": 0,                  # 用户当前魔力值（憨豆）
            "permanent_invite_price": 0, # 永久邀请价格
            "temporary_invite_price": 0  # 憨憨站点无临时邀请
        }
        
        # 初始化BeautifulSoup对象
        soup = BeautifulSoup(html_content, 'html.parser')
        
        try:
            # 1. 查找当前魔力值 - 憨憨站点特定格式
            bonus_text = soup.select_one('.text-base.font-bold:not(.text-\\[\\#F29D38\\])')
            if not bonus_text:
                # 尝试其他可能的选择器
                bonus_text = soup.select_one('div.text-base.font-bold')
            
            if bonus_text:
                bonus_str = bonus_text.get_text(strip=True).replace(',', '')
                try:
                    result["bonus"] = float(bonus_str)
                    logger.info(f"站点 {site_name} 魔力值(憨豆): {result['bonus']}")
                except ValueError:
                    logger.warning(f"站点 {site_name} 无法解析魔力值: {bonus_text.get_text(strip=True)}")
            
            # 2. 查找邀请价格 - 寻找包含"邀请名额"的块
            invite_divs = soup.find_all(lambda tag: tag.name == 'div' and '邀请名额' in tag.get_text())
            
            for div in invite_divs:
                # 找到邀请名额对应的价格
                price_div = div.find_next_sibling('div', class_='break-all')
                if price_div:
                    price_text = price_div.get_text(strip=True)
                    # 移除逗号后转换为数字
                    try:
                        price = float(price_text.replace(',', ''))
                        result["permanent_invite_price"] = price
                        logger.info(f"站点 {site_name} 永久邀请价格: {price}")
                        # 找到价格后退出循环
                        break
                    except ValueError:
                        logger.warning(f"站点 {site_name} 无法解析邀请价格: {price_text}")
            
            return result
            
        except Exception as e:
            logger.error(f"解析站点 {site_name} 魔力值商店失败: {str(e)}")
            return result
    
    def _parse_hhclub_homepage(self, site_name: str, html_content: str) -> Dict[str, Any]:
        """
        解析憨憨站点主页，获取邀请数量（从用户弹出面板）
        :param site_name: 站点名称
        :param html_content: HTML内容
        :return: 邀请数量
        """
        result = {
            "permanent_count": 0,
            "temporary_count": 0
        }
        
        try:
            # 初始化BeautifulSoup对象
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 查找用户信息面板
            user_panel = soup.select_one('#user-info-panel')
            if user_panel:
                logger.info(f"站点 {site_name} 找到用户信息面板")
                
                # 查找包含邀请图标和链接的行
                invite_elements = user_panel.select('.flex.flex-row.items-center')
                for elem in invite_elements:
                    # 检查是否有包含"邀请"的img标签
                    img = elem.select_one('img[src*="invite"][alt="邀请"]')
                    if img:
                        # 找到包含邀请数量的div
                        invite_div = elem.select_one('a[href*="invite.php"] div.text-sm')
                        if invite_div:
                            invite_text = invite_div.get_text(strip=True)
                            # 正则匹配邀请数量，格式可能是 [邀请]:&nbsp;&nbsp;0
                            invite_match = re.search(r'\[邀请\]:[\s&nbsp;]*(\d+)', invite_text)
                            if invite_match:
                                try:
                                    result["permanent_count"] = int(invite_match.group(1))
                                    logger.info(f"站点 {site_name} 从用户面板元素精确匹配到邀请数量: 永久={result['permanent_count']}")
                                except (ValueError, TypeError):
                                    logger.warning(f"站点 {site_name} 无法将用户面板元素中的邀请数量转换为整数: {invite_match.group(1)}")
                            else:
                                logger.warning(f"站点 {site_name} 找到邀请元素但未能提取邀请数量: {invite_text}")
            
        except Exception as e:
            logger.error(f"站点 {site_name} 解析主页邀请数量失败: {str(e)}")
        
        return result 