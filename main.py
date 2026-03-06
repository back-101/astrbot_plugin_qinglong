#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstrBot 青龙面板管理插件 (AI 增强版)
版本: 1.1.2
修复内容：补全环境变量的禁用/启用工具函数，防止 AI 误调 Shell。
"""

import time
from typing import Dict, List, Optional, Tuple, Any
import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 常量配置
DEFAULT_TIMEOUT = 10
TOKEN_EXPIRE_SECONDS = 6 * 24 * 3600 

class QinglongAPI:
    """青龙面板 API 封装（异步增强版）"""
    def __init__(self, host: str, client_id: str, client_secret: str):
        self.host = host.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None
        self.token_expire: float = 0
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_token(self) -> bool:
        try:
            if self.token and time.time() < self.token_expire:
                return True
            client = await self._get_client()
            response = await client.get(
                f"{self.host}/open/auth/token",
                params={"client_id": self.client_id, "client_secret": self.client_secret}
            )
            result = response.json()
            if result.get('code') == 200:
                self.token = result['data']['token']
                self.token_expire = time.time() + TOKEN_EXPIRE_SECONDS
                return True
            return False
        except Exception as e:
            logger.error(f"QL Auth Error: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
    
    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Any = None) -> Tuple[bool, Any]:
        if not await self.get_token(): return False, "认证失败"
        try:
            client = await self._get_client()
            url = f"{self.host}{endpoint}"
            resp = await client.request(method, url, headers=self._get_headers(), params=params, json=json_data)
            res = resp.json()
            return (True, res.get('data', {})) if res.get('code') == 200 else (False, res.get('message', '未知错误'))
        except Exception as e:
            return False, str(e)

    # ------ 接口逻辑 ------
    async def get_envs(self, search: str = ""):
        success, data = await self._request("GET", "/open/envs", params={"searchValue": search})
        return data if success else []

    async def disable_envs(self, ids: List[int]):
        return await self._request("PUT", "/open/envs/disable", json_data=ids)

    async def enable_envs(self, ids: List[int]):
        return await self._request("PUT", "/open/envs/enable", json_data=ids)

    async def get_crons(self, search: str = ""):
        success, data = await self._request("GET", "/open/crons", params={"searchValue": search})
        if not success: return []
        return data.get('data', []) if isinstance(data, dict) else data

    async def run_cron(self, ids: List[int]): return await self._request("PUT", "/open/crons/run", json_data=ids)
    async def get_log(self, id: int): return await self._request("GET", f"/open/crons/{id}/log")

@register("astrbot_plugin_qinglong", "Haitun", "青龙面板管理(AI修复版)", "1.1.2")
class QinglongPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.ql_api = QinglongAPI(
            config.get("qinglong_host", "http://172.17.0.1:5700"),
            config.get("qinglong_client_id", ""),
            config.get("qinglong_client_secret", "")
        )

    @filter.command("ql")
    async def ql_command(self, event: AstrMessageEvent):
        """控制台物理指令"""
        if not event.is_admin:
            yield event.plain_result("🚫 权限不足")
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("💡 用法: /ql ls, /ql envs, /ql disable <id>")
            return

        cmd = parts[1].lower()
        if cmd == "envs":
            kw = parts[2] if len(parts) > 2 else ""
            envs = await self.ql_api.get_envs(kw)
            res = "💎 **环境变量**:\n" + "\n".join([f"{'🟢' if e['status']==0 else '🔴'} `{e['id']}` | {e['name']}" for e in envs[:10]])
            yield event.plain_result(res)
        
        elif cmd in ["disable", "enable"] and len(parts) > 2:
            func = self.ql_api.disable_envs if cmd == "disable" else self.ql_api.enable_envs
            success, msg = await func([int(parts[2])])
            yield event.plain_result(f"✅ 操作成功" if success else f"❌ 失败: {msg}")

    # ==========================================
    # LLM 工具函数 (AI 专用)
    # ==========================================

    @filter.llm_tool(name="ql_get_envs")
    async def ai_get_envs(self, event: AstrMessageEvent, search_keyword: str = ""):
        """获取或搜索环境变量列表。"""
        envs = await self.ql_api.get_envs(search_keyword)
        if not envs: return "未找到匹配的环境变量。"
        res = "找到以下变量：\n"
        for e in envs[:10]:
            res += f"- ID: {e['id']} | 名称: {e['name']} | 状态: {'启用' if e['status']==0 else '禁用'}\n"
        return res

    @filter.llm_tool(name="ql_disable_env")
    async def ai_disable_env(self, event: AstrMessageEvent, env_id: int):
        """禁用指定 ID 的环境变量。请先调用 ql_get_envs 获取正确 ID。"""
        success, msg = await self.ql_api.disable_envs([env_id])
        return f"环境变量 {env_id} 禁用{'成功' if success else '失败: ' + msg}"

    @filter.llm_tool(name="ql_enable_env")
    async def ai_enable_env(self, event: AstrMessageEvent, env_id: int):
        """启用指定 ID 的环境变量。"""
        success, msg = await self.ql_api.enable_envs([env_id])
        return f"环境变量 {env_id} 启用{'成功' if success else '失败: ' + msg}"

    @filter.llm_tool(name="ql_get_crons")
    async def ai_get_crons(self, event: AstrMessageEvent, search_keyword: str = ""):
        """查看定时任务列表。"""
        crons = await self.ql_api.get_crons(search_keyword)
        if not crons: return "未找到相关任务。"
        res = "任务列表如下：\n"
        for c in crons[:10]:
            res += f"- ID: {c['id']} | 名称: {c.get('name')}\n"
        return res

    async def terminate(self):
        await self.ql_api.close()
