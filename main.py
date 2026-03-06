import time
from typing import Dict, List, Optional, Tuple, Any
import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

class QinglongAPI:
    def __init__(self, host: str, client_id: str, client_secret: str):
        self.host = host.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expire = 0
        self._client = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def get_token(self) -> bool:
        if self.token and time.time() < self.token_expire: return True
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.host}/open/auth/token", params={"client_id": self.client_id, "client_secret": self.client_secret})
            res = resp.json()
            if res.get('code') == 200:
                self.token = res['data']['token']
                self.token_expire = time.time() + (6 * 24 * 3600)
                return True
            return False
        except Exception as e:
            logger.error(f"QL Auth Error: {e}")
            return False

    async def _request(self, method: str, endpoint: str, params=None, json_data=None):
        if not await self.get_token(): return False, "认证失败"
        try:
            client = await self._get_client()
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            resp = await client.request(method, f"{self.host}{endpoint}", headers=headers, params=params, json=json_data)
            res = resp.json()
            return (True, res.get('data', {})) if res.get('code') in [200, 201] else (False, res.get('message', '操作失败'))
        except Exception as e:
            return False, str(e)

@register("astrbot_plugin_qinglong", "Haitun", "青龙全能管家(AI版)", "1.1.8")
class QinglongPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.ql_api = QinglongAPI(
            config.get("qinglong_host", ""),
            config.get("qinglong_client_id", ""),
            config.get("qinglong_client_secret", "")
        )

    # ==========================================
    # 1. 环境变量管理 (ENV)
    # ==========================================

    @filter.llm_tool(name="ql_env_search")
    async def ql_env_search(self, event: AstrMessageEvent, keyword: str = ""):
        """
        搜索或查看环境变量。支持搜索关键词，分页显示。
        Args:
            keyword (string): 搜索关键词，为空则查看前10个。
        """
        success, data = await self.ql_api._request("GET", "/open/envs", params={"searchValue": keyword})
        if not success: return f"获取失败: {data}"
        envs = data if isinstance(data, list) else data.get('data', [])
        if not envs: return "没有找到相关环境变量。"
        res = [f"ID:{e['id']} | {e['name']} | {'🟢' if e['status']==0 else '🔴禁用'} | 备注:{e.get('remarks')}" for e in envs[:12]]
        return "环境变量列表(前12条):\n" + "\n".join(res)

    @filter.llm_tool(name="ql_env_add")
    async def ql_env_add(self, event: AstrMessageEvent, name: str, value: str, remarks: str = ""):
        """
        添加一个新的环境变量。
        Args:
            name (string): 变量名 (如 JD_COOKIE)
            value (string): 变量值
            remarks (string): 备注信息
        """
        success, msg = await self.ql_api._request("POST", "/open/envs", json_data=[{"name": name, "value": value, "remarks": remarks}])
        return f"✅ 变量 `{name}` 添加成功" if success else f"❌ 添加失败: {msg}"

    @filter.llm_tool(name="ql_env_update")
    async def ql_env_update(self, event: AstrMessageEvent, env_id: int, name: str, value: str, remarks: str = ""):
        """
        更新现有的环境变量。
        Args:
            env_id (number): 变量的数字 ID。
            name (string): 变量名
            value (string): 变量值
            remarks (string): 备注
        """
        success, msg = await self.ql_api._request("PUT", "/open/envs", json_data={"id": env_id, "name": name, "value": value, "remarks": remarks})
        return f"✅ ID:{env_id} 更新成功" if success else f"❌ 更新失败: {msg}"

    @filter.llm_tool(name="ql_env_action")
    async def ql_env_action(self, event: AstrMessageEvent, action: str, env_id: int):
        """
        对环境变量执行 启用、禁用、删除 操作。
        Args:
            action (string): 可选 'enable'(启用), 'disable'(禁用), 'delete'(删除)
            env_id (number): 变量的数字 ID。
        """
        method = "DELETE" if action == "delete" else "PUT"
        endpoint = f"/open/envs/{action}" if action != "delete" else "/open/envs"
        success, msg = await self.ql_api._request(method, endpoint, json_data=[env_id])
        return f"✅ 环境变量 ID:{env_id} {action} 成功" if success else f"❌ 操作失败: {msg}"

    # ==========================================
    # 2. 定时任务管理 (CRON)
    # ==========================================

    @filter.llm_tool(name="ql_cron_search")
    async def ql_cron_search(self, event: AstrMessageEvent, keyword: str = ""):
        """
        查看或搜索定时任务。
        Args:
            keyword (string): 任务名称关键词。
        """
        success, data = await self.ql_api._request("GET", "/open/crons", params={"searchValue": keyword})
        tasks = data.get('data', []) if isinstance(data, dict) else data
        if not tasks: return "未找到任务。"
        res = [f"ID:{t['id']} | {t['name']} | {'🟢运行中' if t['status']==0 else '🔴停止'}" for t in tasks[:10]]
        return "定时任务列表:\n" + "\n".join(res)

    @filter.llm_tool(name="ql_cron_action")
    async def ql_cron_action(self, event: AstrMessageEvent, action: str, cron_id: int):
        """
        对定时任务执行 运行、停止、启用、禁用、置顶、取消置顶、删除 操作。
        Args:
            action (string): 可选 'run'(执行), 'stop'(停止), 'enable'(启用), 'disable'(禁用), 'pin'(置顶), 'unpin'(取消置顶), 'delete'(删除)
            cron_id (number): 任务的数字 ID。
        """
        method = "DELETE" if action == "delete" else "PUT"
        path_map = {"delete": "", "pin": "pin", "unpin": "unpin"}
        endpoint = f"/open/crons/{path_map.get(action, action)}"
        if action == "delete": endpoint = "/open/crons"
        success, msg = await self.ql_api._request(method, endpoint, json_data=[cron_id])
        return f"✅ 任务 ID:{cron_id} {action} 指令执行成功" if success else f"❌ 失败: {msg}"

    @filter.llm_tool(name="ql_cron_log")
    async def ql_cron_log(self, event: AstrMessageEvent, cron_id: int):
        """
        查看定时任务的最近运行日志。
        Args:
            cron_id (number): 任务的数字 ID。
        """
        success, log = await self.ql_api._request("GET", f"/open/crons/{cron_id}/log")
        return f"📄 任务日志尾部：\n{log[-800:]}" if success else "日志读取失败。"

    # ==========================================
    # 3. 系统信息 (SYSTEM)
    # ==========================================

    @filter.llm_tool(name="ql_system_info")
    async def ql_system_info(self, event: AstrMessageEvent):
        """获取青龙面板系统版本和运行状态。"""
        success, data = await self.ql_api._request("GET", "/open/system")
        if not success: return "获取失败。"
        return f"🖥️ 青龙 v{data.get('version')} | 运行模式：{'集群' if data.get('is_cluster') else '独立'}"

    @filter.command("ql")
    async def ql_help(self, event: AstrMessageEvent):
        yield event.plain_result("🌟 青龙 AI 管家已全面就绪！\n支持查/增/改/删/启/禁变量，以及跑/停/顶/看日志任务。\n快试试对我说：'查下百度变量' 或 '看看任务ID为5的日志'！")

    async def terminate(self):
        if self.ql_api._client: await self.ql_api._client.aclose()
