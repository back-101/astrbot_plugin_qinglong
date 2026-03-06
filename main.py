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
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def get_token(self):
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
        if not await self.get_token(): return False, "青龙认证失败，请检查配置"
        try:
            client = await self._get_client()
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            resp = await client.request(method, f"{self.host}{endpoint}", headers=headers, params=params, json=json_data)
            res = resp.json()
            return (True, res.get('data', {})) if res.get('code') in [200, 201] else (False, res.get('message', '未知错误'))
        except Exception as e:
            return False, f"网络异常: {str(e)}"

@register("astrbot_plugin_qinglong", "Haitun", "青龙全能管家", "1.2.8")
class QinglongPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.ql_api = QinglongAPI(
            config.get("qinglong_host", ""), # 默认使用你提供的IP
            config.get("qinglong_client_id", ""),
            config.get("qinglong_client_secret", "")
        )

    # ==========================================
    # AI工具 1：环境变量大师 (Env Expert)
    # ==========================================
    @filter.llm_tool(name="manage_envs")
    async def manage_envs(self, event: AstrMessageEvent, action: str, ids: List[int] = None, name: str = "", value: str = "", remarks: str = ""):
        """
        管理环境变量。action可选: search(查), add(增), update(改), delete(删), enable(启), disable(禁)。
        """
        if not event.is_admin: return "🚫 只有管理员才能动环境变量喔！"
        if isinstance(ids, int): ids = [ids]

        if action == "search":
            success, data = await self.ql_api._request("GET", "/open/envs", params={"searchValue": name or ""})
            return "\n".join([f"ID:{e['id']} | {e['name']} | {'🟢启用' if e['status']==0 else '🔴禁用'}" for e in data[:15]]) if success else "未找到相关变量。"
        
        elif action == "add":
            success, msg = await self.ql_api._request("POST", "/open/envs", json_data=[{"name": name, "value": value, "remarks": remarks or f"AI添加于{time.strftime('%m-%d')}"}])
            return f"✅ 变量 `{name}` 已成功添加！" if success else f"❌ 失败: {msg}"
            
        elif action == "update" and ids:
            success, msg = await self.ql_api._request("PUT", "/open/envs", json_data={"id": ids[0], "name": name, "value": value, "remarks": remarks})
            return f"✅ ID:{ids[0]} 更新完成！" if success else f"❌ 失败: {msg}"
            
        elif action in ["enable", "disable", "delete"]:
            if not ids: return "请告诉我 ID 号。"
            method = "DELETE" if action == "delete" else "PUT"
            endpoint = f"/open/envs/{action}" if method == "PUT" else "/open/envs"
            success, msg = await self.ql_api._request(method, endpoint, json_data=ids)
            return f"✅ 变量 {action} 操作已执行。" if success else f"❌ 失败: {msg}"

    # ==========================================
    # AI工具 2：任务调度专家 (Cron Expert)
    # ==========================================
    @filter.llm_tool(name="manage_crons")
    async def manage_crons(self, event: AstrMessageEvent, action: str, ids: List[int] = None, keyword: str = ""):
        """
        全权管理定时任务。action可选: search(查), run(跑), stop(停), enable(启), disable(禁), pin(置顶), unpin(取消置顶), delete(删), log(看日志)。
        """
        if not event.is_admin: return "🚫 权限不足。"
        if isinstance(ids, int): ids = [ids]

        if action == "search":
            success, data = await self.ql_api._request("GET", "/open/crons", params={"searchValue": keyword})
            tasks = data.get('data', []) if isinstance(data, dict) else data
            return "\n".join([f"ID:{t['id']} | {t['name']} | {'🟢' if t['status']==0 else '🔴'}" for t in tasks[:10]]) if success else "任务查询失败。"
        
        elif action == "log" and ids:
            success, log = await self.ql_api._request("GET", f"/open/crons/{ids[0]}/log")
            return f"📄 任务 {ids[0]} 日志尾部：\n{log[-800:]}" if success else f"❌ 日志读取失败。"
            
        elif action in ["run", "stop", "enable", "disable", "pin", "unpin", "delete"]:
            if not ids: return "请告诉我任务 ID。"
            method = "DELETE" if action == "delete" else "PUT"
            endpoint = f"/open/crons/{action}" if action not in ["delete", "pin", "unpin"] else f"/open/crons/{action}"
            # 特殊修正：删除、置顶、取消置顶的路径
            if action == "delete": endpoint = "/open/crons"
            success, msg = await self.ql_api._request(method, endpoint, json_data=ids)
            return f"✅ 任务 {action} 操作成功！" if success else f"❌ 失败: {msg}"

    # ==========================================
    # AI工具 3：系统信息 (System Info)
    # ==========================================
    @filter.llm_tool(name="get_ql_system")
    async def get_ql_system(self, event: AstrMessageEvent):
        """查询青龙面板的版本和运行状态。"""
        success, data = await self.ql_api._request("GET", "/open/system")
        if not success: return "系统信息获取失败。"
        return f"🖥️ 青龙面板 v{data.get('version')}\n多机模式：{'开启' if data.get('is_cluster') else '关闭'}"

    @filter.command("ql")
    async def ql_help(self, event: AstrMessageEvent):
        yield event.plain_result("🌟 青龙全能管家指令已解锁！\n你可以直接对我说：\n- '查找京东变量并禁用'\n- '运行脚本 520 并把日志发给我'\n- '把那个包含 BING 的任务置顶'\n- '当前青龙版本是多少？'")

    async def terminate(self):
        if self.ql_api._client: await self.ql_api._client.aclose()
