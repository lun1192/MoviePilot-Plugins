import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.utils.string import StringUtils

lock = threading.Lock()


class QBRssBrush(_PluginBase):
    # 插件名称
    plugin_name = "QB RSS刷流管理"
    # 插件描述
    plugin_desc = "自动控制qBittorrent的RSS下载和上传流量管理"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "lun"
    # 作者主页
    author_url = "https://github.com/lun1192/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "qbrssbrush_"
    # 加载顺序
    plugin_order = 22
    # 可使用的用户级别
    auth_level = 2


    # 私有属性
    downloader_helper = None
    _event = threading.Event()
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _notify = False
    # pause/delete
    _downloaders = []
    _action = "pause"

    
    # 新增属性
    _rss_enabled = False
    _rss_interval = 15
    _rss_name = ""
    _rss_regex = ""
    _rss_category= None
    _rss_size_limit = 10000.0
    _rss_upspeed_min = 0
    _rss_upspeed_max = 0
    _rss_aging_time = 0
    _processed_torrents = set()

    def init_plugin(self, config: dict = None):
        self.downloader_helper = DownloaderHelper()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._downloaders = config.get("downloaders") or []
            self._action = config.get("action")
            
            # 新增配置项
            self._rss_enabled = config.get("rss_enabled", False)
            self._rss_interval = int(config.get("rss_interval", 15))
            self._rss_name = config.get("rss_name", "")
            self._rss_regex = config.get("rss_regex", "")
            self._rss_category = config.get("rss_category", None)
            self._rss_size_limit = float(config.get("rss_size_limit", 10000.0))
            self._rss_upspeed_min = int(config.get("rss_upspeed_min", 0))
            self._rss_upspeed_max = int(config.get("rss_upspeed_max", 0))
            self._rss_aging_time = int(config.get("rss_aging_time", 0))

            if self._rss_interval < 10:
                self._rss_interval = 10
        self.stop_service()

        if self.get_state() or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"自动删种服务启动，立即运行一次")
                self._scheduler.add_job(func=self.refresh_rss_and_delete_torrents, trigger='date',
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False
                # 保存设置
                self.update_config({
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                    "action": self._action,
                    "downloaders": self._downloaders,
                    "rss_enabled": self._rss_enabled,
                    "rss_interval": self._rss_interval,
                    "rss_name": self._rss_name,
                    "rss_regex": self._rss_regex,
                    "rss_category": self._rss_category,
                    "rss_size_limit": self._rss_size_limit,
                    "rss_upspeed_min": self._rss_upspeed_min,
                    "rss_upspeed_max": self._rss_upspeed_max,
                    "rss_aging_time": self._rss_aging_time
                })
                if self._scheduler and not self._scheduler.get_jobs():
                    self._scheduler.shutdown()
                    self._scheduler = None
                if self._scheduler.get_jobs():
                    # 启动服务
                    self._scheduler.print_jobs()
                    self._scheduler.start()
                

    def get_state(self) -> bool:
        return True if self._enabled and self._rss_interval and self._downloaders else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        services = []
        if self.get_state():
            services.append({
                "id": "TorrentRemover",
                "name": "Rss订阅刷流任务",
                "trigger": "interval",
                "func": self.refresh_rss_and_delete_torrents,
                "kwargs": {"minutes": self._rss_interval}
            })
        
        
        return services

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'rss_enabled',
                                            'label': '启用RSS刷新控制',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_interval',
                                            'label': '刷新间隔（分钟）',
                                            'type': 'number'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 5
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '动作',
                                            'items': [
                                                {'title': '暂停', 'value': 'pause'},
                                                {'title': '删除种子', 'value': 'delete'},
                                                {'title': '删除种子和文件', 'value': 'deletefile'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 5
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.downloader_helper.get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_name',
                                            'label': 'RSS订阅名称',
                                            'placeholder': '多个rss使用","(半角)分割'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_category',
                                            'label': '下载任务分类',
                                            'placeholder': '只支持1个'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_size_limit',
                                            'label': '指定分类任务总体积上限(GB)',
                                            'type': 'number',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_upspeed_min',
                                            'label': '种子最小上传速度(kB/s)',
                                            'type': 'number',
                                            'placeholder': '种子小于该值将被删除'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_upspeed_max',
                                            'label': '下载器最大上传速度(kB/s)',
                                            'type': 'number',
                                            'placeholder': '超过该值不再进行rss刷新'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_aging_time',
                                            'label': 'rss订阅过期时间(分钟)',
                                            'type': 'number',
                                            'placeholder': '超过该时间的rss订阅将被忽略'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,

                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'rss_regex',
                                            'label': '过滤正则表达式',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '自动删种存在风险，如设置不当可能导致数据丢失！建议动作先选择暂停，确定条件正确后再改成删除。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '目前只支持qb下载器，RSS订阅源需要手动在qb的webui处添加。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "action": 'pause',
            'downloaders': [],
            "rss_enabled": False,
            "rss_interval": 15
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = self.downloader_helper.get_services(name_filters=self._downloaders)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    def __get_downloader(self, name: str):
        """
        根据类型返回下载器实例
        """
        return self.service_infos.get(name).instance

    def __get_downloader_config(self, name: str):
        """
        根据类型返回下载器实例配置
        """
        return self.service_infos.get(name).config

    def refresh_rss_and_delete_torrents(self):
        """
        定时删除下载器中的下载任务
        """
        for downloader in self._downloaders:
            try:
                with lock:

                    downloader_config = self.__get_downloader_config(downloader)
        
                    if downloader_config.type != "qbittorrent":
                        logger.warning(f"RSS刷新功能仅支持qBittorrent")
                        return
                    
                    # 检查下载器整体上传速度，优先保证上传速度
                    if self._rss_upspeed_max > 0:
                        avg_upspeed = self.__get_average_upspeed(downloader)
                
                        if avg_upspeed >= self._rss_upspeed_max:
                            logger.info(f"当前上传速度 {avg_upspeed:.2f}KB/s 已超过上限 {self._rss_upspeed_max}KB/s，暂停RSS刷新和种子删除")
                            return
                    
                    # 获取需删除种子列表
                    torrents = self.get_remove_torrents(downloader)
                    logger.info(f"自动删种任务 获取符合处理条件种子数 {len(torrents)}")
                    if len(torrents) > 0:
                        # 删除种子
                        downlader_obj = self.__get_downloader(downloader)
                        if self._action == "pause":
                            message_text = f"{downloader.title()} 共暂停{len(torrents)}个种子"
                            for torrent in torrents:
                                if self._event.is_set():
                                    logger.info(f"自动删种服务停止")
                                    return
                                text_item = f"{torrent.get('name')} " \
                                            f"来自站点：{torrent.get('site')} " \
                                            f"大小：{StringUtils.str_filesize(torrent.get('size'))} " \
                                            f"上传大小：{StringUtils.str_filesize(torrent.get('upsize'))}"
                                # 暂停种子
                                downlader_obj.stop_torrents(ids=[torrent.get("id")])
                                logger.info(f"自动删种任务 暂停种子：{text_item}")
                                message_text = f"{message_text}\n{text_item}"
                        elif self._action == "delete":
                            message_text = f"{downloader.title()} 共删除{len(torrents)}个种子"
                            for torrent in torrents:
                                if self._event.is_set():
                                    logger.info(f"自动删种服务停止")
                                    return
                                text_item = f"{torrent.get('name')} " \
                                            f"来自站点：{torrent.get('site')} " \
                                            f"大小：{StringUtils.str_filesize(torrent.get('size'))} " \
                                            f"上传大小：{StringUtils.str_filesize(torrent.get('upsize'))}"
                                # 删除种子
                                downlader_obj.delete_torrents(delete_file=False,
                                                            ids=[torrent.get("id")])
                                logger.info(f"自动删种任务 删除种子：{text_item}")
                                message_text = f"{message_text}\n{text_item}"
                        elif self._action == "deletefile":
                            message_text = f"{downloader.title()} 共删除{len(torrents)}个种子及文件"
                            for torrent in torrents:
                                if self._event.is_set():
                                    logger.info(f"自动删种服务停止")
                                    return
                                text_item = f"{torrent.get('name')} " \
                                            f"来自站点：{torrent.get('site')} " \
                                            f"大小：{StringUtils.str_filesize(torrent.get('size'))} " \
                                            f"上传大小：{StringUtils.str_filesize(torrent.get('upsize'))}"
                                # 删除种子
                                downlader_obj.delete_torrents(delete_file=True,
                                                            ids=[torrent.get("id")])
                                logger.info(f"自动删种任务 删除种子及文件：{text_item}")
                                message_text = f"{message_text}\n{text_item}"
                        if torrents and message_text and self._notify:
                            self.post_message(
                                mtype=NotificationType.SiteMessage,
                                title=f"【自动删种任务完成】",
                                text=message_text
                            )

                    # 检查是否需要刷新RSS
                    if self._rss_enabled:
                        # 检查分类任务总体积
                        remain_size = self._rss_size_limit - self.__get_category_size(downloader, self._rss_category)
                        if remain_size > 0.0:
                            #刷新rss，并下载新种子
                            self.refresh_rss(downloader, remain_size)
                        else:
                            logger.info(f"分类 {self._rss_category} 总体积已达到上限 {self._rss_size_limit:.2f}GB，暂停RSS刷新")
            except Exception as e:
                logger.error(f"自动删种任务异常：{str(e)}")
                
    def __get_category_size(self, downloader: str, category: str | None) -> float:
        """
        获取指定分类的任务总大小(GB)
        """
        try:
            # 下载器对象
            downloader_obj = self.__get_downloader(downloader)
            torrents = downloader_obj.qbc.torrents_info(category=category)
            # 计算总大小
            total_size = sum(torrent.size for torrent in torrents)
            
            # 转换为GB
            total_size_gb = total_size / 1024 / 1024 / 1024
            logger.info(f"分类 {category} 当前总体积: {total_size_gb:.2f}GB")
            return total_size_gb
        except Exception as e:
            logger.error(f"获取分类大小异常：{str(e)}")
            return 0
    
    def __get_average_upspeed(self, downloader: str) -> float:
        """
        获取下载器的平均上传速度(MB/s)
        """
        try:
            # 下载器对象
            downloader_obj = self.__get_downloader(downloader)
            
            # 获取全局传输信息
            transfer_info = downloader_obj.qbc.transfer_info()
            if not transfer_info:
                return 0
            
            # 获取上传速度(B/s)并转换为MB/s
            up_speed = transfer_info.get('up_info_speed', 0) / 1024
            logger.info(f"当前下载器平均上传速度: {up_speed:.2f}KB/s")
            return up_speed
        except Exception as e:
            logger.error(f"获取上传速度异常：{str(e)}")
            return 0
    def __get_rss_items(self, downloader: str, rss_name: str):
        try:
            # 刷新RSS
            downloader_obj = self.__get_downloader(downloader)
            if rss_name:
                # 获取所有RSS源
                rss_feeds = downloader_obj.qbc.rss.items()
                # 查找特定RSS源
                if rss_name not in rss_feeds:
                    logger.warning(f"未找到名为'{rss_name}'的RSS源")
                    return []
                #刷新RSS
                downloader_obj.qbc.rss.refresh_item(rss_name) 
            else:
                logger.warning(f"未指定RSS源")
                return []
            # 获取该RSS源中的所有文章
            articles = downloader_obj.qbc.rss.items.with_data(rss_name)["articles"]
            rss_items = []
            # 获取当前时间（UTC时间）
            current_time = datetime.now(pytz.UTC)
            time_threshold = current_time - timedelta(minutes=self._rss_aging_time)

            # 处理每篇文章
            for article_data in articles:
                article_title = article_data.get("title")
                article_link = article_data.get("torrentURL")
                article_date = article_data.get("date")
                item_date = datetime.strptime(article_date, '%d %b %Y %H:%M:%S %z')
                # 过滤掉过时的文章    
                if self._rss_aging_time > 0 and item_date < time_threshold:
                    continue
                # 使用正则表达式匹配体积大小，只考虑GB，并提取纯数字
                match = re.search(r'\[(\d+(\.\d+)?)\s*GB\]', article_title)
                if match is None:
                    continue
                # 如果文章未处理过且有下载链接
                if article_title and article_link and article_title not in self._processed_torrents:
                    rss_items.append(
                            {
                                "title": article_title,
                                "url": article_link,
                                "size": match.group(1)  # 纯数字,GB
                            }
                    )
                    
            logger.info(f"RSS检查完成，新增{len(rss_items)}个文章")
            return rss_items
        except Exception as e:
            logger.error(f"处理RSS源时出错: {e}")
            return []
    def refresh_rss(self, downloader: str, remain_size: float):
        """
        刷新RSS并添加下载任务
        """
        if not self._downloaders or not self._rss_name:
            logger.info("RSS刷新条件不满足，跳过")
            return
        try:
            downloader_obj = self.__get_downloader(downloader)
                       
            added_count = 0
            total_size = 0.0  # 用于存储总大小
            added_items = []  # 用于存储添加的任务名称
            #刷新RSS并添加下载任务
            rss_names = self._rss_name.split(",")
            for rss_name in rss_names:

                logger.info(f"开始刷新RSS: {self._rss_name}")
                # 获取RSS条目
                rss_items = self.__get_rss_items(downloader, rss_name)
                if not rss_items:
                    logger.info(f"RSS {self._rss_name} 没有新的条目")
                    return
                
                # 根据正则表达式过滤条目
                for item in rss_items:
                    item_title = item.get("title", "")
                    item_url = item.get("url", "")
                    item_size = float(item.get("size", ""))
                    # 使用正则表达式匹配
                    if re.search(self._rss_regex, item_title):
                        if item_size > remain_size:
                            logger.info(f"任务体积过大，剩余空间（{remain_size:.2f}GB）不足，跳过: {item_title}")
                            continue
                        # 添加下载任务
                        logger.info(f"添加下载任务: {item_title}")
                        success = downloader_obj.add_torrent(
                            content=item_url,
                            is_paused=False,
                            download_dir=None,
                            category=self._rss_category,
                            tag=None
                        )
                        
                        if success:
                            added_count += 1
                            total_size += item_size  # 累加总大小
                            added_items.append(item_title)  # 收集添加的任务名称
                            if len(self._processed_torrents) > 1000:  # 设置一个合理的上限
                                self._processed_torrents = set(list(self._processed_torrents)[-500:])
                            self._processed_torrents.add(item_title)
                            remain_size = remain_size - item_size
                        else:
                            logger.error(f"添加下载任务失败: {item_title}")
            
            if added_count > 0:
                added_items_str = ', '.join(added_items)
                logger.info(f"本次RSS刷新共添加了 {added_count} 个下载任务，总大小为 {total_size:.2f}GB，剩余空间 {remain_size:.2f}GB，任务名称: {added_items_str}")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【RSS刷新完成】",
                        text=f"本次RSS刷新共添加了 {added_count} 个下载任务，总大小为 {total_size:.2f}GB，剩余空间 {remain_size:.2f}GB，任务名称: {added_items_str}"
                    )
            else:
                logger.info(f"本次RSS刷新没有添加新的下载任务")
        except Exception as e:
            logger.error(f"RSS刷新异常：{str(e)}")

    def __get_qb_torrent(self, torrent: Any) -> Optional[dict]:
        """
        检查QB下载任务是否符合条件
        """
        # 完成时间
        date_done = torrent.completion_on if torrent.completion_on > 0 else torrent.added_on
        # 现在时间
        date_now = int(time.mktime(datetime.now().timetuple()))
        # 做种时间
        torrent_seeding_time = date_now - date_done if date_done else 0
        # 平均上传速度
        torrent_upload_avs = torrent.uploaded / torrent_seeding_time if torrent_seeding_time else 0
        # 瞬时上传速度
        torrent_upload_speed = torrent.upspeed
        """
        sizes = self._size.split('-') if self._size else []
        minsize = float(sizes[0]) * 1024 * 1024 * 1024 if sizes else 0
        maxsize = float(sizes[-1]) * 1024 * 1024 * 1024 if sizes else 0
        
        # 分享率
        if self._ratio and torrent.ratio <= float(self._ratio):
            return None
        # 做种时间 单位：小时
        if self._time and torrent_seeding_time <= float(self._time) * 3600:
            return None
        # 文件大小
        if self._size and (torrent.size >= int(maxsize) or torrent.size <= int(minsize)):
            return None

        if self._pathkeywords and not re.findall(self._pathkeywords, torrent.save_path, re.I):
            return None
        if self._trackerkeywords and not re.findall(self._trackerkeywords, torrent.tracker, re.I):
            return None
        if self._torrentstates and torrent.state not in self._torrentstates:
            return None
        """
        if self._rss_category and (not torrent.category or torrent.category != self._rss_category):
            return None
        if self._rss_upspeed_min and torrent_upload_avs >= float(self._rss_upspeed_min) * 1024:
            return None
        if torrent_upload_speed >= float(self._rss_upspeed_min) * 1024:
            return None
        return {
            "id": torrent.hash,
            "name": torrent.name,
            "site": StringUtils.get_url_sld(torrent.tracker),
            "size": torrent.size,
            "upsize": torrent.uploaded
        }

    def get_remove_torrents(self, downloader: str): 
        """
        获取自动删种任务种子
        """
        remove_torrents = []
        # 下载器对象
        downloader_obj = self.__get_downloader(downloader)
        # 查询种子
        torrents = downloader_obj.get_completed_torrents()
        if not torrents:
            logger.error(f"自动删种任务，获取种子列表失败")
            return []
        # 处理种子
        for torrent in torrents:
            item = self.__get_qb_torrent(torrent)
            if not item:
                continue
            remove_torrents.append(item)
        # 处理辅种
        return remove_torrents
