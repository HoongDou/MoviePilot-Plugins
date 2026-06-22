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
from app.utils.site import SiteUtils



class UBitsSignIn(_PluginBase):
    # 插件名称
    plugin_name = "UBits 自动签到"
    # 插件描述
    plugin_desc = "自动签到 UBits.club，支持定时签到、结果通知。"
    # 插件图标
    plugin_icon = "signin.png"
    # 插件版本
    plugin_version = "1.2"
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

    # 定时器
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
        # 停止已有任务
        self.stop_service()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = config.get("cron") or ""
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify"))
        self._cookie = config.get("cookie") or ""
        self._ua = config.get("ua") or ""
        self._proxy = bool(config.get("proxy"))

        # 立即运行一次
        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("UBits 自动签到：立即运行一次")
            self._scheduler.add_job(
                func=self.sign_in,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                + timedelta(seconds=3),
                name="UBits 签到",
            )
            # 关闭一次性开关并保存
            self._onlyonce = False
            self._save_config()

            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def _save_config(self):
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
            logger.error(f"UBits 签到定时任务配置错误：{err}")
            return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # 第一行：开关
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
                    # 第二行：执行周期
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
                    # 第三行：Cookie
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
                                            "placeholder": "登录 UBits.club 后从浏览器复制 Cookie",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    # 第四行：UA
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
                                            "placeholder": "留空使用默认 UA",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    # 说明
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
                                            "text": "Cookie 获取方法：登录 UBits.club 后，"
                                            "按 F12 打开开发者工具，"
                                            "在 Application → Cookies 中复制所有 Cookie，"
                                            "或在 Network 请求头中复制 cookie 字段。",
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
                                            "text": "Cookie 有效期有限，失效后需重新填写。"
                                            "签到成功不等同于站点认定为活跃，请结合站点公告自行判断。",
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
        详情页：展示最近 30 条签到历史
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
                                    "text": "mdi-check-circle"
                                    if success
                                    else "mdi-alert-circle",
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
        执行签到，可由定时任务、立即运行、远程命令触发
        """
        if event:
            event_data = event.event_data or {}
            if event_data.get("action") != "ubits_signin":
                return
            logger.info("UBits 签到：收到远程命令")
            self.post_message(
                channel=event_data.get("channel"),
                title="开始 UBits 签到 ...",
                userid=event_data.get("user"),
            )

        if not self._cookie:
            logger.warn("UBits 签到：未配置 Cookie，跳过")
            return

        success, message = self._do_signin()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 追加历史记录，保留最近 30 条
        history: List[dict] = self.get_data("history") or []
        history.append({"date": now_str, "success": success, "message": message})
        history = history[-30:]
        self.save_data("history", history)

        logger.info(f"UBits 签到结果：{message}")

        if self._notify:
            self.post_message(
                title="【UBits 自动签到】",
                mtype=NotificationType.SiteMessage,
                text=f"{'✅' if success else '❌'} {message}\n时间：{now_str}",
            )

        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title=f"UBits 签到{'成功' if success else '失败'}：{message}",
                userid=event.event_data.get("user"),
            )

    def _do_signin(self) -> Tuple[bool, str]:
        """
        核心签到逻辑：GET attendance.php，解析返回内容
        """
        proxies = settings.PROXY if self._proxy else None
        timeout = 60

        logger.info(f"UBits 签到：请求 {self._signin_url}")

        try:
            res = RequestUtils(
                cookies=self._cookie,
                ua=self._ua or None,
                proxies=proxies,
                timeout=timeout,
            ).get_res(url=self._signin_url)

            if res is None:
                logger.info("UBits 签到：attendance.php 无响应，尝试访问首页")
                res = RequestUtils(
                    cookies=self._cookie,
                    ua=self._ua or None,
                    proxies=proxies,
                    timeout=timeout,
                ).get_res(url=self._site_url)
                if res is None:
                    return False, "签到失败，无法访问站点"

            if res.status_code not in [200, 403, 500]:
                return False, f"签到失败，状态码：{res.status_code}"

            # Cloudflare 拦截
            if under_challenge(res.text):
                return False, "签到失败，被 Cloudflare 拦截，建议开启代理"

            # 解析签到结果

            # 1. 本次签到成功，提取奖励 U币
            #    页面格式：本次签到获得 <b>10</b> 个U币
            bonus_match = re.search(
                r"本次签到获得\s*<[^>]+>\s*(\d+)\s*</[^>]+>\s*个U币",
                res.text,
            )
            if bonus_match:
                return True, f"签到成功，获得 {bonus_match.group(1)} U币"

            # 2. 页面标题含"签到成功"（兜底，防止页面结构变化）
            if re.search(r"<h2[^>]*>\s*签到成功\s*</h2>", res.text):
                return True, "签到成功"

            # 3. 今日已签到 — 导航栏出现"签到已得N"说明之前已签过
            already_match = re.search(r"签到已得(\d+)", res.text)
            if already_match:
                return True, f"今日已签到，已得 {already_match.group(1)} U币"

            # 4. Cookie 失效
            if not SiteUtils.is_logged_in(res.text):
                return False, "签到失败，Cookie 已失效，请重新填写"

            # 5. 能登录但未识别到具体结果
            return True, "签到完成（未识别到具体返回文字）"

        except Exception as e:
            logger.error(f"UBits 签到异常：{e}")
            return False, f"签到失败：{e}"

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"UBits 签到：停止服务失败：{e}")
