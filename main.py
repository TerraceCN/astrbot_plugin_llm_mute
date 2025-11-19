# -*- coding: utf-8 -*-

from datetime import datetime
import json
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

from .utils import sec2str, ts2str


@register(
    "astrbot_plugin_llm_mute",
    "LLMMute",
    "AstrBot 大模型生成禁言控制",
    "0.0.1",
)
class LLMMutePlugin(Star):
    PERSISTENCE_FILE_PATH = "data/llm_mute/data.json"

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.muted_until: dict[str, float] = {}  # 各sid禁言结束时间
        self.generating: set[str] = set()  # 正在生成的sid
        self.last_generated: dict[str, float] = {}  # 上一次sid响应结束时间

    async def initialize(self):
        if self.config["persistence"]["enabled"]:
            self._load()

    async def terminate(self):
        if self.config["persistence"]["enabled"]:
            self._save()

    def _save(self):
        """保存数据"""

        try:
            file_path = Path(self.PERSISTENCE_FILE_PATH)
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True)
            with file_path.open("w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "muted_until": self.muted_until,
                        "last_generated": self.last_generated,
                    },
                    fp,
                    ensure_ascii=False,
                    indent=4,
                )
        except Exception as e:
            logger.error(f"LLMMute 持久化数据保存失败: {e}")

    def _load(self):
        """加载数据"""

        try:
            file_path = Path(self.PERSISTENCE_FILE_PATH)
            if not file_path.exists():
                return
            with file_path.open("r", encoding="utf-8") as fp:
                data: dict = json.load(fp)
                self.muted_until = data.get("muted_until") or dict()
                self.last_generated = data.get("last_generated") or dict()
            logger.info("LLMMute 持久化数据加载成功")
        except Exception as e:
            logger.error(f"LLMMute 持久化数据加载失败: {e}")

    def _is_muted(self, sid: str):
        """该会话是否被禁言"""

        if sid not in self.muted_until:
            return False

        current_ts = datetime.now().timestamp()
        unmute_ts = self.muted_until[sid]
        if current_ts < unmute_ts:
            return True
        else:
            self.muted_until.pop(sid, None)
            return False

    def _mute(self, sid: str, duration: int | None = None):
        """禁言会话"""

        if duration is None:
            duration = int(self.config["mute_command"]["default_duration"])

        muted_until = datetime.now().timestamp() + duration
        self.muted_until[sid] = muted_until
        logger.info(
            f"LLM 禁言 {sec2str(duration)}, 结束时间: {ts2str(muted_until)} ({sid=})"
        )

        if self.config["persistence"]["enabled"]:
            self._save()

    def _unmute(self, sid: str):
        """解除会话禁言"""

        if sid not in self.muted_until:
            return False

        self.muted_until.pop(sid, None)
        logger.info(f"LLM 解除禁言 ({sid=})")

        if self.config["persistence"]["enabled"]:
            self._save()

        return True

    def get_mute_left_time(self, sid: str):
        """获取会话禁言剩余时间"""

        if sid not in self.muted_until:
            return "未禁言"

        current_ts = datetime.now().timestamp()
        unmute_ts = self.muted_until[sid]
        total = unmute_ts - current_ts

        return sec2str(total)

    def get_mute_until_time(self, sid: str):
        """获取会话禁言结束时间"""

        if sid not in self.muted_until:
            return "未禁言"

        return ts2str(self.muted_until[sid])

    @filter.on_llm_request()
    async def on_llm_req(
        self, event: AstrMessageEvent, request: ProviderRequest, *args, **kwargs
    ):
        """LLM 请求拦截"""

        sid = event.get_session_id()
        msg_time = event.message_obj.timestamp

        if self._is_muted(sid):
            logger.info(
                f"LLM 禁言中, 忽略请求 ({sid=}, 剩余时间: {self.get_mute_left_time(sid)})"
            )
            event.stop_event()
            return

        last_generated = self.last_generated.get(sid, 0)
        logger.debug(f"消息时间: {msg_time}, 上次响应时间: {last_generated}")
        if msg_time - last_generated < self.config["llm_interval"]["interval"]:
            logger.info(f"LLM 请求间隔过短, 忽略请求 ({sid=})")
            event.stop_event()
            return

        if sid in self.generating:
            logger.info(f"LLM 正在生成中, 忽略请求 ({sid=})")
            event.stop_event()
            return

        self.generating.add(sid)

    @filter.on_llm_response()
    async def on_llm_resp(
        self, event: AstrMessageEvent, resp: LLMResponse, *args, **kwargs
    ):
        """LLM 响应结束记录"""
        sid = event.get_session_id()

        if sid in self.generating:
            self.generating.remove(sid)  # 移除生成标记
        self.last_generated[sid] = datetime.now().timestamp()  # 记录响应结束时间

    @filter.command("llm_mute")
    async def llm_mute_command(
        self, event: AstrMessageEvent, duration: int | None = None
    ):
        """禁言 LLM 指令 /llm_mute"""

        sid = event.get_session_id()
        if self.config["mute_command"]["enabled"] and event.is_admin():
            if duration is None:
                self._mute(sid)
            else:
                self._mute(sid, duration)
            yield event.plain_result(
                (
                    f"已禁言 LLM {self.get_mute_left_time(sid)}\n"
                    f"解封时间: {self.get_mute_until_time(sid)}"
                )
            )

    @filter.command("llm_unmute")
    async def llm_unmute_command(self, event: AstrMessageEvent):
        """解除 LLM 禁言指令 /llm_unmute"""

        sid = event.get_session_id()
        if (
            self.config["mute_command"]["enabled"]
            and event.is_admin()
            and self._unmute(sid)
        ):
            yield event.plain_result("已解除 LLM 禁言")
