import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.helper.cloudflare import under_challenge
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class UBitsSignIn(_PluginBase):
    # 插件名称
    plugin_name = "UBits 自动签到"
    # 插件描述
    plugin_desc = "自动签到 UBits.club，支持定时签到、结果通知。"
    # 插件图标，建议放在 plugins.v2/ubitsignin/signin.png
    plugin_icon = "signin.png"
    # 插件版本
    plugin_version = "1.2.0"
    # 插件作者
    plugin_author = "HoongDou"
    # 作者主页
    author_url = "https://github.com/HoongDou"
    # 配置项ID前缀，必须唯一
    plugin_config_prefix = "ubitsignin_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 定时器，仅用于立即运行一次
    _scheduler: Optional[BackgroundScheduler] = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _onlyonce: bool = False
    _notify: bool = False
    _cookie: str = ""
    _ua: str = ""
    _proxy: bool = False

    # 签到地址
    _signin_url = "https://ubits.club/attendance.php"
    _site_url = "https://ubits.club/"

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置。
        MoviePilot 会在插件加载、保存配置后调用。
        """
        self.stop_service()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = config.get("cron") or ""
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify"))
        self._cookie = config.get("cookie") or ""
        self._ua = config.get("ua") or ""
        self._proxy = bool(config.get("proxy"))

        if self._onlyonce:
            self._run_once()

    def _run_once(self):
        """
        立即运行一次。
        使用独立 BackgroundScheduler，避免影响 MoviePilot 全局服务调度。
        """
        try:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("UBits 自动签到：准备立即运行一次")

            self._scheduler.add_job(
                func=self.sign_in,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="UBits 自动签到",
            )

            self._onlyonce = False
            self._save_config()

            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        except Exception as e:
            logger.error(f"UBits 自动签到：立即运行任务创建失败：{e}")

    def get_state(self) -> bool:
        return self._enabled

    def _save_config(self):
        """
        保存当前配置。
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "cron": self._cron,
                "onlyonce": self._onlyonce,
                "notify": self._notify,
                "cookie": self._cookie,
                "ua": self._ua,
                "proxy": self._proxy,
            }
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册远程命令。
        """
        return [
            {
                "cmd": "/ubits_signin",
                "event": EventType.PluginAction,
                "desc": "UBits 签到",
                "category": "站点",
                "data": {"action": "ubits_signin"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册 MoviePilot 定时服务。
        """
        if not self._enabled or not self._cron:
            return []

        try:
            return [
                {
                    "id": "UBitsSignIn",
                    "name": "UBits 自动签到",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.sign_in,
                    "kwargs": {},
                }
            ]
        except Exception as err:
            logger.error(f"UBits 自动签到：定时任务配置错误：{err}")
            return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        插件配置页面。
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "proxy",
                                            "label": "使用代理",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "5位cron表达式，如 0 8 * * *",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cookie",
                                            "label": "Cookie",
                                            "placeholder": "登录 UBits.club 后从浏览器复制完整 Cookie",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ua",
                                            "label": "User-Agent",
                                            "placeholder": "建议填写获取 Cookie 时同一浏览器的 User-Agent",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": (
                                                "Cookie 获取方法：登录 UBits.club 后，"
                                                "按 F12 打开开发者工具，在 Application -> Cookies 中复制 Cookie，"
                                                "或在 Network 请求头中复制 cookie 字段。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": (
                                                "如果站点启用了 Cloudflare，Cookie 里通常需要包含 cf_clearance，"
                                                "并且 User-Agent 要和获取 Cookie 时保持一致。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "proxy": False,
            "cron": "0 8 * * *",
            "cookie": "",
            "ua": "",
        }

    def get_page(self) -> List[dict]:
        """
        插件详情页，展示最近 30 条签到历史。
        """
        history: List[dict] = self.get_data("history") or []

        if not history:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无签到记录，请先配置 Cookie 并运行一次。",
                        "prepend-icon": "mdi-information",
                    },
                }
            ]

        history = list(reversed(history))[:30]

        rows = []
        for record in history:
            success = record.get("success", False)
            rows.append(
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"class": "text-start"},
                            "text": record.get("date", ""),
                        },
                        {
                            "component": "td",
                            "props": {"class": "text-start"},
                            "text": record.get("message", ""),
                        },
                        {
                            "component": "td",
                            "props": {"class": "text-center"},
                            "content": [
                                {
                                    "component": "VIcon",
                                    "props": {
                                        "color": "success" if success else "error",
                                        "size": "small",
                                    },
                                    "text": "mdi-check-circle" if success else "mdi-alert-circle",
                                }
                            ],
                        },
                    ],
                }
            )

        return [
            {
                "component": "VTable",
                "props": {"hover": True, "density": "compact"},
                "content": [
                    {
                        "component": "thead",
                        "content": [
                            {
                                "component": "tr",
                                "content": [
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start"},
                                        "text": "时间",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start"},
                                        "text": "结果",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-center"},
                                        "text": "状态",
                                    },
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": rows},
                ],
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def sign_in(self, event: Event = None):
        """
        执行签到。
        可由定时任务、立即运行一次、远程命令触发。
        """
        if event:
            event_data = event.event_data or {}
            if event_data.get("action") != "ubits_signin":
                return

            logger.info("UBits 自动签到：收到远程命令")

            self.post_message(
                channel=event_data.get("channel"),
                title="开始 UBits 签到 ...",
                userid=event_data.get("user"),
            )

        if not self._cookie:
            logger.warning("UBits 自动签到：未配置 Cookie，跳过")
            return

        success, message = self._do_signin()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        history: List[dict] = self.get_data("history") or []
        history.append(
            {
                "date": now_str,
                "success": success,
                "message": message,
            }
        )
        history = history[-30:]
        self.save_data("history", history)

        logger.info(f"UBits 自动签到：{message}")

        if self._notify:
            self.post_message(
                title="【UBits 自动签到】",
                mtype=NotificationType.SiteMessage,
                text=f"{'✅' if success else '❌'} {message}\n时间：{now_str}",
            )

        if event:
            event_data = event.event_data or {}
            self.post_message(
                channel=event_data.get("channel"),
                title=f"UBits 签到{'成功' if success else '失败'}：{message}",
                userid=event_data.get("user"),
            )

    def _do_signin(self) -> Tuple[bool, str]:
        """
        核心签到逻辑。
        使用 Cookie 请求 attendance.php，并根据页面内容判断签到结果。
        """
        proxies = settings.PROXY if self._proxy else None
        timeout = 60

        headers = self._build_headers()

        logger.info(f"UBits 自动签到：请求 {self._signin_url}")

        try:
            res = RequestUtils(
                headers=headers,
                proxies=proxies,
                timeout=timeout,
            ).get_res(url=self._signin_url)

            if res is None:
                logger.warning("UBits 自动签到：attendance.php 无响应，尝试访问首页")
                res = RequestUtils(
                    headers=headers,
                    proxies=proxies,
                    timeout=timeout,
                ).get_res(url=self._site_url)

                if res is None:
                    return False, "签到失败，无法访问站点"

            logger.info(
                f"UBits 自动签到：HTTP {res.status_code}，最终地址：{getattr(res, 'url', '')}"
            )

            if res.status_code not in [200, 403, 500]:
                return False, f"签到失败，状态码：{res.status_code}"

            html = res.text or ""

            if under_challenge(html):
                return False, "签到失败，被 Cloudflare 拦截，请检查代理、Cookie 和 User-Agent"

            if self._is_cookie_invalid(res, html):
                return False, "签到失败，Cookie 可能已失效，请重新填写"

            success, message = self._parse_signin_result(html)
            if success is not None:
                return success, message

            return True, "签到完成，但未识别到具体返回文字"

        except Exception as e:
            logger.error(f"UBits 自动签到异常：{e}")
            return False, f"签到失败：{e}"

    def _build_headers(self) -> Dict[str, str]:
        """
        构造请求头。
        对 Cloudflare 站点来说，Cookie 和 User-Agent 最好与浏览器保持一致。
        """
        user_agent = self._ua or getattr(
            settings,
            "USER_AGENT",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        return {
            "Cookie": self._cookie,
            "User-Agent": user_agent,
            "Referer": self._site_url,
            "Origin": self._site_url.rstrip("/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    @staticmethod
    def _is_cookie_invalid(res, html: str) -> bool:
        """
        判断 Cookie 是否失效。
        这里不要过度依赖 MoviePilot 的 SiteUtils，因为不同站点页面结构不同。
        """
        final_url = getattr(res, "url", "") or ""

        if "login.php" in final_url:
            return True

        invalid_keywords = [
            "login.php",
            "takelogin.php",
            "登录",
            "登入",
            "用户名",
            "密码",
        ]

        logged_in_keywords = [
            "logout.php",
            "userdetails.php",
            "attendance.php",
            "签到",
            "控制面板",
        ]

        has_invalid_keyword = any(keyword in html for keyword in invalid_keywords)
        has_logged_in_keyword = any(keyword in html for keyword in logged_in_keywords)

        return has_invalid_keyword and not has_logged_in_keyword

    @staticmethod
    def _parse_signin_result(html: str) -> Tuple[Optional[bool], str]:
        """
        解析签到页面结果。
        返回：
        - True/False 表示已识别成功或失败
        - None 表示未识别
        """
        bonus_match = re.search(
            r"本次签到获得\s*<[^>]+>\s*(\d+)\s*</[^>]+>\s*个U币",
            html,
            re.S,
        )
        if bonus_match:
            return True, f"签到成功，获得 {bonus_match.group(1)} U币"

        bonus_match = re.search(
            r"本次签到获得\s*(\d+)\s*个U币",
            html,
            re.S,
        )
        if bonus_match:
            return True, f"签到成功，获得 {bonus_match.group(1)} U币"

        if re.search(r"<h2[^>]*>\s*签到成功\s*</h2>", html, re.S):
            return True, "签到成功"

        already_match = re.search(r"签到已得\s*(\d+)", html, re.S)
        if already_match:
            return True, f"今日已签到，已得 {already_match.group(1)} U币"

        already_keywords = [
            "今天已签到",
            "今日已签到",
            "已经签到",
            "您今天已经签到过",
        ]
        if any(keyword in html for keyword in already_keywords):
            return True, "今日已签到"

        fail_keywords = [
            "签到失败",
            "发生错误",
            "非法请求",
            "权限不足",
        ]
        for keyword in fail_keywords:
            if keyword in html:
                return False, f"签到失败，页面提示：{keyword}"

        return None, ""

    def stop_service(self):
        """
        停止立即运行一次使用的独立调度器。
        MoviePilot 自身注册的 get_service 定时任务不在这里处理。
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()

                if self._scheduler.running:
                    self._scheduler.shutdown()

                self._scheduler = None

        except Exception as e:
            logger.error(f"UBits 自动签到：停止服务失败：{e}")
