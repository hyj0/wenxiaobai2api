import asyncio
import json
import random
import uuid
import datetime
import time
import re
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, AsyncGenerator, Tuple
import httpx
import logging
import hashlib
import base64
import hmac
import re
import requests_debugger

requests_debugger.set(output_format=requests_debugger.CURL, max_depth=requests_debugger.MAX_DEPTH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


# 添加配置类来管理API配置
class Config:
    API_KEY = "TkoWuEN8cpDJubb7Zfwxln16NQDZIc8z"
    BASE_URL = "https://api-bj.wenxiaobai.com/api/v1.0"
    BOT_ID = 200006
    DEFAULT_MODEL = "DeepSeek-R1"


# 添加会话管理类
class SessionManager:
    def __init__(self):
        self.device_id = None
        self.token = None
        self.user_id = None
        self.conversation_id = None

    def initialize(self):
        """初始化会话"""
        self.device_id = generate_device_id()
        self.token, self.user_id = get_auth_token(self.device_id)
        self.conversation_id = create_conversation(self.device_id, self.token, self.user_id)
        logger.info(f"Session initialized: user_id={self.user_id}, conversation_id={self.conversation_id}")

    def is_initialized(self):
        """检查会话是否已初始化"""
        return all([self.device_id, self.token, self.user_id, self.conversation_id])

    async def refresh_if_needed(self):
        """如果需要，刷新会话"""
        if not self.is_initialized():
            self.initialize()
    def get_session_json_str(self):
        return json.dumps({"__SESSION0xFE819635__":{"device_id": self.device_id,
                    "token": self.token,
                    "user_id": self.user_id,
                    "conversation_id": self.conversation_id}})

# 创建会话管理器实例
session_manager = SessionManager()


class Message(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0
    frequency_penalty: Optional[float] = 0
    user: Optional[str] = None


class ModelData(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str
    permission: List[Dict[str, Any]] = []
    root: str
    parent: Optional[str] = None


def generate_device_id() -> str:
    """生成设备ID"""
    return f"{uuid.uuid4().hex}_{int(time.time() * 1000)}_{random.randint(100000, 999999)}"


def generate_timestamp() -> str:
    """生成符合要求的UTC时间字符串"""
    timestamp_ms = int(time.time() * 1000) + 559
    utc_time = datetime.datetime.utcfromtimestamp(timestamp_ms / 1000.0)
    return utc_time.strftime('%a, %d %b %Y %H:%M:%S GMT')


def calculate_sha256(data: str) -> str:
    """计算SHA-256摘要"""
    sha256 = hashlib.sha256(data.encode()).digest()
    return base64.b64encode(sha256).decode()


def generate_signature(timestamp: str, digest: str) -> str:
    """生成请求签名"""
    message = f"x-date: {timestamp}\ndigest: SHA-256={digest}"
    signature = hmac.new(
        Config.API_KEY.encode(),
        message.encode(),
        hashlib.sha1
    ).digest()
    return base64.b64encode(signature).decode()


def create_common_headers(timestamp: str, digest: str, token: Optional[str] = None,
                          device_id: Optional[str] = None) -> dict:
    """创建通用请求头"""
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'authorization': f'hmac username="web.1.0.beta", algorithm="hmac-sha1", headers="x-date digest", signature="{generate_signature(timestamp, digest)}"',
        'content-type': 'application/json',
        'digest': f'SHA-256={digest}',
        'origin': 'https://www.wenxiaobai.com',
        'priority': 'u=1, i',
        'referer': 'https://www.wenxiaobai.com/',
        'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
        'x-date': timestamp,
        'x-yuanshi-appname': 'wenxiaobai',
        'x-yuanshi-appversioncode': '2.1.5',
        'x-yuanshi-appversionname': '2.8.0',
        'x-yuanshi-channel': 'browser',
        'x-yuanshi-devicemode': 'Edge',
        'x-yuanshi-deviceos': '134',
        'x-yuanshi-locale': 'zh',
        'x-yuanshi-platform': 'web',
        'x-yuanshi-timezone': 'Asia/Shanghai',
    }

    if token:
        headers['x-yuanshi-authorization'] = f'Bearer {token}'

    if device_id:
        headers['x-yuanshi-deviceid'] = device_id

    return headers


def get_auth_token(device_id: str) -> Tuple[str, str]:
    """获取认证令牌"""
    timestamp = generate_timestamp()
    payload = {
        'deviceId': device_id,
        'device': 'Edge',
        'client': 'tourist',
        'phone': device_id,
        'code': device_id,
        'extraInfo': {'url': 'https://www.wenxiaobai.com/chat/tourist'},
    }
    data = json.dumps(payload, separators=(',', ':'))
    digest = calculate_sha256(data)

    headers = create_common_headers(timestamp, digest)

    try:
        response = httpx.post(
            f"{Config.BASE_URL}/user/sessions",
            headers=headers,
            content=data,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result['data']['token'], result['data']['user']['id']
    except httpx.RequestError as e:
        logger.error(f"获取认证令牌失败: {e}")
        raise HTTPException(status_code=500, detail=f"认证失败: {str(e)}")
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"解析认证响应失败: {e}")
        raise HTTPException(status_code=500, detail="服务器返回了无效的认证数据")


def create_conversation(device_id: str, token: str, user_id: str) -> str:
    """创建新的会话"""
    timestamp = generate_timestamp()
    payload = {'visitorId': device_id}
    data = json.dumps(payload, separators=(',', ':'))
    digest = calculate_sha256(data)

    headers = create_common_headers(timestamp, digest, token, device_id)

    try:
        response = httpx.post(
            f"{Config.BASE_URL}/core/conversations/users/{user_id}/bots/{Config.BOT_ID}/conversation",
            headers=headers,
            content=data,
            timeout=30
        )
        response.raise_for_status()
        return response.json()['data']
    except httpx.RequestError as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"解析会话响应失败: {e}")
        raise HTTPException(status_code=500, detail="服务器返回了无效的会话数据")


def is_thinking_content(content: str) -> bool:
    """判断内容是否为思考过程"""
    return "```ys_think" in content


def clean_thinking_content(content: str) -> str:
    """清理思考过程内容，移除特殊标记"""
    # 移除整个思考块
    if "```ys_think" in content:
        # 使用正则表达式移除整个思考块
        cleaned = re.sub(r'```ys_think.*?```', '', content, flags=re.DOTALL)
        # 如果清理后只剩下空白字符，返回空字符串
        if cleaned and cleaned.strip():
            return cleaned.strip()
        return ""
    return content


# 辅助函数：验证 API 密钥
async def verify_api_key(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    api_key = authorization.replace("Bearer ", "").strip()
    if api_key != Config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


def create_chunk(sse_id: str, created: int, content: Optional[str] = None,
                 is_first: bool = False, meta: Optional[dict] = None,
                 finish_reason: Optional[str] = None) -> dict:
    """创建响应块"""
    delta = {}

    if content is not None:
        if is_first:
            delta = {"role": "assistant", "content": content}
        else:
            delta = {"content": content}

    if meta is not None:
        delta["meta"] = meta

    return {
        "id": f"chatcmpl-{sse_id}",
        "object": "chat.completion.chunk",
        "created": created,
        "model": Config.DEFAULT_MODEL,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason
        }]
    }


async def process_message_event(data: dict, is_first_chunk: bool, in_thinking_block: bool,
                                thinking_started: bool, thinking_content: list, web_search_content: str, web_search_link_map: map) -> Tuple[str, bool, bool, bool, list]:
    """处理消息事件"""
    content = data.get("content", "")
    pattern = r'\[(\d+)\]\(@ref\)'
    matches = re.findall(pattern, content)
    for n in matches:
        url = web_search_link_map [n]
        content = content.replace (f"[{n}](@ref)", f"[{n}]({url})")

    timestamp = data.get("timestamp", "")
    created = int(timestamp) // 1000 if timestamp else int(time.time())
    sse_id = data.get('sseId', str(uuid.uuid4()))
    result = ""

    # 检查是否是思考块的开始
    if "```ys_think" in content and not thinking_started:
        thinking_started = True
        in_thinking_block = True
        # 发送思考块开始标记
        chunk = create_chunk(
            sse_id=sse_id,
            created=created,
            content="<think>__SESSION0xFE819635__\n\n" + web_search_content,
            is_first=is_first_chunk
        )
        result = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        return result, in_thinking_block, thinking_started, is_first_chunk, thinking_content

    # 检查是否是思考块的结束
    if "```" in content and in_thinking_block:
        in_thinking_block = False
        # 发送思考块结束标记
        chunk = create_chunk(
            sse_id=sse_id,
            created=created,
            content="\n</think>\n\n"
        )
        result = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        return result, in_thinking_block, thinking_started, is_first_chunk, thinking_content

    # 如果在思考块内，收集思考内容
    if in_thinking_block:
        thinking_content.append(content)
        # 在思考块内也发送内容，但标记为思考内容
        chunk = create_chunk(
            sse_id=sse_id,
            created=created,
            content=content
        )
        result = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        return result, in_thinking_block, thinking_started, is_first_chunk, thinking_content

    # 清理内容，移除思考块
    content = clean_thinking_content(content)
    if not content:  # 如果清理后内容为空，跳过
        return result, in_thinking_block, thinking_started, is_first_chunk, thinking_content

    # 正常发送内容
    chunk = create_chunk(
        sse_id=sse_id,
        created=created,
        content=content,
        is_first=is_first_chunk
    )
    result = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    return result, in_thinking_block, thinking_started, False, thinking_content


def process_generate_end_event(data: dict, in_thinking_block: bool, thinking_content: list) -> List[str]:
    """处理生成结束事件"""
    result = []
    timestamp = data.get("timestamp", "")
    created = int(timestamp) // 1000 if timestamp else int(time.time())
    sse_id = data.get('sseId', str(uuid.uuid4()))

    # 如果思考块还没有结束，发送结束标记
    if in_thinking_block:
        end_thinking_chunk = create_chunk(
            sse_id=sse_id,
            created=created,
            content="\n</think>\n\n"
        )
        result.append(f"data: {json.dumps(end_thinking_chunk, ensure_ascii=False)}\n\n")

    # 添加元数据
    meta_chunk = create_chunk(
        sse_id=sse_id,
        created=created,
        meta={"thinking_content": "".join(thinking_content) if thinking_content else None}
    )
    result.append(f"data: {json.dumps(meta_chunk, ensure_ascii=False)}\n\n")

    # 发送结束标记
    end_chunk = create_chunk(
        sse_id=sse_id,
        created=created,
        finish_reason="stop"
    )
    result.append(f"data: {json.dumps(end_chunk, ensure_ascii=False)}\n\n")
    result.append("data: [DONE]\n\n")
    return result


async def generate_response(messages: List[dict], model: str, temperature: float, stream: bool,
                            max_tokens: Optional[int] = None, presence_penalty: float = 0,
                            frequency_penalty: float = 0, top_p: float = 1.0) -> AsyncGenerator[str, None]:
    """生成响应 - 使用真正的流式处理"""
    # new session or not
    has_session = False
    for i in range(len(messages)):
        msg = messages[len(messages) - 1 - i]
        if "role" in msg.keys():
            if msg['role'] != "assistant":
                continue
            content = msg["content"]
            if content.find("__SESSION0xFE819635__") >= 0:
                has_session = True
                msg["content"] = content.replace("__SESSION0xFE819635__", "")

    if not has_session:
        logger.info("new session!")
        session_manager.initialize()

    # 确保会话已初始化
    await session_manager.refresh_if_needed()

    timestamp = generate_timestamp()
    payload = {
        'userId': session_manager.user_id,
        'botId': Config.BOT_ID,
        'botAlias': 'custom',
        'query': messages[-1]['content'],
        'isRetry': False,
        'breakingStrategy': 0,
        'isNewConversation': True,
        'mediaInfos': [],
        'turnIndex': 0,
        'rewriteQuery': '',
        'conversationId': session_manager.conversation_id,
        'capabilities': [
            {
                'capability': 'otherBot',
                'capabilityRang': 0,
                'defaultQuery': '',
                'icon': 'https://wy-static.wenxiaobai.com/bot-capability/prod/%E6%B7%B1%E5%BA%A6%E6%80%9D%E8%80%83.png',
                'minAppVersion': '',
                'title': '深度思考(R1)',
                'botId': 200004,
                'botDesc': '深度回答这个问题（DeepSeek R1）',
                'selectedIcon': 'https://wy-static.wenxiaobai.com/bot-capability/prod/%E6%B7%B1%E5%BA%A6%E6%80%9D%E8%80%83%E9%80%89%E4%B8%AD.png',
                'botIcon': 'https://platform-dev-1319140468.cos.ap-nanjing.myqcloud.com/bot/avatar/2025/02/06/612cbff8-51e6-4c6a-8530-cb551bcfda56.webp',
                'defaultHidden': False,
                'defaultSelected': False,
                'key': 'deep_think',
                'promptMenu': False,
                'isPromptMenu': False,
                'defaultPlaceholder': '',
                '_id': 'deep_think',
            },
            {
                "icon": "https://wy-static.wenxiaobai.com/bot-capability/prod/fastsearch.png",
                "title": "日常搜索",
                "defaultQuery": "",
                "capability": "otherBot",
                "capabilityRang": 0,
                "minAppVersion": "",
                "botId": 200007,
                "botDesc": "即时获取最新信息",
                "selectedIcon": "https://wy-static.wenxiaobai.com/bot-capability/prod/fastsearch_active.png",
                "botIcon": "https://platform-dev-1319140468.cos.ap-nanjing.myqcloud.com/bot/avatar/2025/02/06/612cbff8-51e6-4c6a-8530-cb551bcfda56.webp",
                "exclusiveCapabilities": [
                    "file",
                    "camera",
                    "image"
                ],
                "defaultSelected": True,
                "defaultHidden": False,
                "key": "quick_search",
                "defaultPlaceholder": "",
                "isPromptMenu": False,
                "subCapabilities": None,
                "promptMenu": False,
                "_is_new_tag": False,
                "web_beta": ""
            }
        ],
        'attachmentInfo': {
            'url': {
                'infoList': [],
            },
        },
        'inputWay': 'proactive',
        'pureQuery': '',
    }
    data = json.dumps(payload, separators=(',', ':'))
    digest = calculate_sha256(data)

    # 创建流式请求的特殊头部
    headers = create_common_headers(timestamp, digest, session_manager.token, session_manager.device_id)
    headers.update({
        'accept': 'text/event-stream, text/event-stream',
        'x-yuanshi-appversioncode': '',
        'x-yuanshi-appversionname': '3.1.0',
    })

    try:
        # 使用 stream=True 参数，实现真正的流式处理
        async with httpx.AsyncClient(timeout=httpx.Timeout(900)) as client:
            async with client.stream('POST', f"{Config.BASE_URL}/core/conversation/chat/v1",
                                     headers=headers, content=data) as response:
                response.raise_for_status()

                # 处理流式响应
                is_first_chunk = True
                current_event = None
                in_thinking_block = False
                thinking_content = []
                thinking_started = False
                web_search_content = ""
                web_search_link_map = {}

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        current_event = None
                        continue
                    print(line)
                    # 解析事件类型
                    if line.startswith("event:"):
                        current_event = line[len("event:"):].strip()
                        continue

                    # 处理数据行
                    elif line.startswith("data:"):
                        json_str = line[len("data:"):].strip()
                        try:
                            '''
                            event:opened
data:{"querySentenceId":"ba19b0a9-4ad9-4b05-94f4-27fef8ce98a3","turnId":"aa2e2e75-f179-41ac-b81f-072e0ebce8e8","timestamp":"1744605113347","conversationId":"37192559-cf33-4409-acaf-b094112ab3a8","sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","queryTime":"2025-04-14T12:31:53.34642121","answerSentenceId":"65032a52-2f30-46e6-81d2-a4bb482ffe6b"}

event:onlineSearch
data:{"sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","content":{"details":[{"stage":"thoughtDetail","title":"这是个生活领域的事实查询任务，问题比较简单，我可以直接回答。","content":"这是个生活领域的事实查询任务，问题比较简单，我可以直接回答。"}]}}

event:onlineSearch
data:{"sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","content":{"details":[{"stage":"search","title":"正在联网搜索","content":""}]}}

event:onlineSearch
data:{"sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","content":{"details":[{"stage":"webSearchKeywords","title":"3个搜索关键词","content":["深圳 今日天气","深圳 2025年4月14日 天气预报","深圳 晴雨表 今天"]}]}}

event:webSearch
data:{"sub_type":"webSearch","sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","type":"ClientEvent","content":"全网收集资料中"}

event:webSearch
data:{"sub_type":"webSearch","sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","type":"ClientEvent","content":"分析海量数据中"}

event:webSearchDetail
data:{"sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","content":{"title":"为您检索到56篇内容","details":[{"id":"6da1b9df-1fef-49db-96c8-745b3018e5c0","index":"1","title":"深圳市气象局（台）","url":"https://weather.sz.gov.cn/","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/7568097852743828524.ico","hostName":"深圳市气象局","summary":"深圳市气象局门户网站为您提供权威、及时、准确的深圳天气预警、天气预报、天气实况、台风路径、深圳气候等信息服务，为深圳及其周边城市的生产生活提供全面可靠的气象服务","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"98f9bb86-08d6-4f3f-93a2-53f99f5fe35b","index":"2","title":"深圳7天天气详情","url":"https://tianqi.2345.com/today-59493.htm","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/14986605679644698667.ico","hostName":"2345天气预报","summary":"2345天气预报为您提供深圳24小时天气详情、深圳今日 天气预报，包括实时温度、风力风向、空气质量、湿度、气压、降水概率、紫外线强度等，每小时更新一次！ 输入城市、乡镇、街道、景点名称 ...","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"b1a8ac78-37bb-4fce-862d-6168747f9f25","index":"3","title":"天气实况与预报","url":"https://weather.sz.gov.cn/qixiangfuwu/yubaofuwu/jinmingtianqiyubao/index.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/7568097852743828524.ico","hostName":"深圳市气象局","summary":"深圳市气象局门户网站为您提供权威、及时、准确的深圳天气预警、天气预报、天气实况、台风路径、深圳 气候等信息服务，为深圳及其周边城市的生产生活提供全面可靠的气象服务 网站支持IPv6 繁體 English 手机版 数据开放 无障碍阅读 ...","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"9b7a0b8c-f58e-44bb-bb21-d69b97742719","index":"4","title":"深圳天气","url":"https://www.tianqi.com/shenzhen/today/","hostLogo":"","hostName":"","summary":"深圳天气网为您提供深圳天气预报24小时详情、深圳今日天气预报，包括今日实时温度、24小时降水概率、湿度、pm2.5 、风向、紫外线强度等，助您放心出行。 天气网提供全国国内城市天气预报，旅游景点天气预报，国际城市天气预报以及历史 ...","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"6c00bd23-f486-44dd-a222-eda5c972a3b2","index":"5","title":"http://www.nmc.cn/publish/forecast/AGD/shenzuo.html","url":"http://www.nmc.cn/publish/forecast/AGD/shenzuo.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/4109805565254913874.ico","hostName":"中央气象台","summary":"全球天气公报 全球热带气旋监测公报 WMO第XI海区海事天气公报 国外农业气象监测与作物展望 全球灾害性天气监测月报 全球雨雪落区预报 世界气象中心（北京）门户网 一带一路气象服务 亚洲沙尘暴预报专业气象中心","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"2724ba85-a086-4d0f-9b7a-cdcb7d64f56b","index":"6","title":"深圳今天将出现强对流和大风降温天气 防范强雷电和短时大风 铁路部分普速列车停运","url":"https://m.163.com/dy/article/JSUFMJPD0514R9KQ.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/16426760574136675243.ico","hostName":"网易","summary":"深圳今天将出现强对流和大风降温天气 防范强雷电和短时大风 铁路部分普速列车停运,大风,铁路,雷电,气象台,强对流,强雷雨,高温天气","type":"","cTime":"2025-04-12","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-12"},{"id":"12fb89c0-b783-4c52-bef7-5275c9b7e42f","index":"7","title":"最大阵风10级左右，深圳天气黄色“双预警”","url":"http://cj.sina.cn/articles/view/1686546714/6486a91a02002qmd4?finpagefr=p_104","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/5934584009833329958.ico","hostName":"新浪财经","summary":"来源：深圳卫视深视新闻 请注意 深圳市雷雨大风黄色 和暴雨黄色预警信号 正在生效中 【深圳市雷雨大风黄色和暴雨黄色预警信号】深圳市气象台2025年04月12日14时35分发布全市暴雨黄色和雷雨大风黄色预警信号，目前...来源/深圳天气","type":"","cTime":"2025-04-13","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-13"},{"id":"bb740f6d-e759-4d42-ae33-22c35c300525","index":"8","title":"雷雨+9级大风！本周六，深圳将迎来强对流天气！","url":"http://cj.sina.cn/articles/view/1789681642/6aac5fea02701em40?finpagefr=p_104","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/5934584009833329958.ico","hostName":"新浪财经","summary":"深圳这两天的天气如何呢？4月10日—11日：阴天间多云，间中有分散阵雨，天气暖湿，早晚有（轻）雾，气温21℃—28℃；4月12日：受冷暖气流交汇影响，深圳市较大可能有强雷雨大风天气，最大阵风9级以上，气温20℃—25℃，4月12日...","type":"","cTime":"2025-04-12","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-12"},{"id":"8e22b153-0661-4ae8-8067-33f27b781b55","index":"9","title":"天气实况与预报","url":"https://weather.sz.gov.cn/mobile/qixiangfuwu/yubaofuwu/jinmingtianqiyubao/index.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/7568097852743828524.ico","hostName":"深圳市气象局","summary":"多云；气温13-18℃；东北风3级，沿海、高地和海区阵风6级；相对湿度50%-80%。 loading. 湿度%. loading. 日雨量mm. loading. 风向. loading. 风速级.","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"38fa174e-0078-42de-afe2-47702aa25d9f","index":"10","title":"深圳2024年04月天气历史记录","url":"https://www.wentian123.com/guangdong/shenzhen/202404.htm","hostLogo":"","hostName":"","summary":"为你提供快速准确的深圳市天气历史记录,2024年04月的天气记录和气象趋势追踪,主要指标包括每天最高气温、最低气温、天气状况、风向等...","type":"","cTime":"2025-04-07","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-07"},{"id":"9631cf02-d565-4aa0-973c-3822d936f57d","index":"11","title":"2025年4月14日，深圳市：阴天转多云，适合出行","url":"https://www.sohu.com/a/883629363_121976704/","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/7928926881863082255.ico","hostName":"搜狐","summary":"2025年4月14日，深圳市的天气将以阴天开始，随后转为多云。上午的气温在22到24度之间，适合出行。上下班高峰时间，预计交通较为顺畅，但由于天气阴沉，建议 ...","type":"","cTime":"2025-04-13","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-13"},{"id":"da4c0b70-a832-4fd3-94a5-ced6ec70625d","index":"12","title":"【深圳天气】深圳天气预报,蓝天,蓝天预报,雾霾,雾霾消散,天气预报一周,天气预报15天查询","url":"https://www.weather.com.cn/html/weather/101280601.shtml","hostLogo":"","hostName":"","summary":"深圳天气预报，及时准确发布中央气象台天气信息，便捷查询深圳今日天气，深圳周末天气，深圳一周天气预报，深圳蓝天预报，深圳天气预报，深圳40日天气预报，还提供深圳的生活指数、健康指数、交通指数、旅游指数，及时发布深圳气象预警信号、各类气象资讯。","type":"","cTime":"2025-04-11","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-11"},{"id":"14eec698-c29a-47a1-b350-f30bd369ae55","index":"13","title":"深圳天气","url":"https://m.cncn.com/tianqi/shenzhen","hostLogo":"","hostName":"","summary":"多云22 ~ 28 ℃04月11日<3级,无持续风向深圳天气预报04/11 今天 多云 22~28℃ 04/12 明天 大雨转雷阵雨 17~25℃ 04/13 周日 晴 16~25℃ 04/14 周一 晴 17~28℃ 04/15 周二 多...","type":"","cTime":"2025-04-11","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-11"},{"id":"7ebe6e4a-b547-482b-9810-f6a7dd806967","index":"14","title":"深圳市","url":"https://weather.sz.gov.cn/mobile/?ad_check=1","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/7568097852743828524.ico","hostName":"深圳市气象局","summary":"03/28 深圳市气象局关于征求地方标准《高层建筑雷电防护装置维护保养及检测规程》（征求意见稿）意见的通告 常见问题3/29 你好，2024年深圳市光明区全年降雨天数多少天...","type":"","cTime":"2025-04-06","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2025-04-06"},{"id":"e376b6dd-827e-40a7-a365-6c8b3fab02e5","index":"15","title":"深圳光明：打造城市治理中的“晴雨表”","url":"https://cn.chinadaily.com.cn/a/202003/30/WS5e819c37a3107bb6b57a990f.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/15750544434798585462.ico","hostName":"中国日报网","summary":"面临错综复杂的治理环境，这份“晴雨表”能抽丝剥茧，从海量数据中提取关键信息，最终实现城市全状态实时化和可视化、城市管理决策协同化和智能化，驱动城市管理 ...","type":"","cTime":"2020-03-30","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":"2020-03-30"},{"id":"1f159ee6-c88d-48bf-8285-5b379ec042a2","index":"16","title":"广东省, 深圳市 天气预报 | MSN 天气","url":"https://www.msn.cn/zh-cn/weather/forecast/in-%E5%B9%BF%E4%B8%9C%E7%9C%81,%E6%B7%B1%E5%9C%B3%E5%B8%82?loc=eyJsIjoi56aP55Sw5Yy6IiwiciI6IuW5v%2BS4nOecgSIsInIyIjoi5rex5Zyz5biCIiwiYyI6IuS4reWNjuS6uuawkeWFseWSjOWbvSIsImkiOiJDTiIsImciOiJ6aC1jbiIsIngiOiIxMTQuMDU4IiwieSI6IjIyLjU0NCJ9&weadegreetype=C","hostLogo":"","hostName":"","summary":"使用 MSN 天气 获取 广东省, 深圳市, 福田区 今天、晚上和明天的每小时准确预测，以及 10 天每日预测和天气雷达。随时了解降水、严重天气警告、空气质量和野火警报。 想要查看其他位置? 请在此处输入它 主题 ‎°C 广东省, 深圳市,...","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"bd1763dd-479c-4e15-9764-457cc07fdbde","index":"17","title":"深圳天气预报,深圳7天天气预报,深圳15天天气预报,深圳天气查询","url":"https://www.weather.com.cn/weather/101280601.shtml","hostLogo":"","hostName":"","summary":"深圳天气预报，及时准确发布中央气象台天气信息，便捷查询深圳今日天气，深圳周末天气，深圳一周天气预报，深圳蓝天预报，深圳天气预报，深圳40日天气预报，还提供深圳的生活指数、健康指数、交通指数、旅游指数，及时发布深圳气象预警信号、各类气象资讯。","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"f48f3844-2b31-41fb-99fb-10607c63976c","index":"18","title":"深圳-天气预报 - 中央气象台","url":"http://www.nmc.cn/publish/forecast/AGD/shenzuo.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/4109805565254913874.ico","hostName":"中央气象台","summary":"11:00 · 29.2℃. 3.1m/s. 东北风. 1009.4hPa ; 14:00 · 29.8℃. 3.3m/s. 东北风. 1007hPa ; 17:00 · 28.4℃. 3.2m/s. 南风. 1006.1hPa.","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"82ed1ff7-e792-4b95-9ef1-1460985a61b2","index":"19","title":"深圳雷达图 - 中国天气网","url":"https://www.weather.com.cn/weather1d/101280601.shtml","hostLogo":"","hostName":"","summary":"气温倒挂！今天北方气温回升率先转为偏暖南方阴雨继续气温低迷. 今天（3月31日），北方气温率先回升至较常年偏高，而南方伴随 ...","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""},{"id":"23245ddc-6e19-41b1-b3ca-22c8e4634228","index":"20","title":"深圳 - 中国气象局-天气预报-城市预报","url":"https://weather.cma.cn/web/weather/59493.html","hostLogo":"https://wy-static.wenxiaobai.com/website/icon/17573544513683138180.ico","hostName":"中国气象局","summary":"星期日 04/13 · 22℃. 17℃ ; 星期一 04/14 · 27℃. 18℃ ; 星期二 04/15 · 30℃. 19℃ ; 星期三 04/16 · 28℃. 20℃ ; 星期四 04/17 · 28℃. 23℃.","type":"","cTime":"","pdfHtmlUrl":"","pdfPublishInfo":"","pdfPublishYear":"","pdfCitedCount":0,"ctime":""}],"totalCount":56,"source":"日常搜索","sourceIcon":"https://wy-static.wenxiaobai.com/bot-capability/prod/fastsearch_active.png"}}

event:webSearch
data:{"sub_type":"webSearch","sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","type":"ClientEvent","content":"精细整理优化中"}

event:message
data:{"contentIndex":11,"timestamp":"1744605119355","sseId":"f092ee67-466a-487c-9bab-0acdb953eb8f","content":"```ys_think\n\n<icon>https://wy-static.wenxiaobai.com/bot-capability/prod/%E6%B7%B1%E5%BA%A6%E6%80%9D%E8%80%83.png</icon>\n\n<start>思考中...</start>\n\n嗯"}
                            '''
                            data = json.loads(json_str)
                            if current_event == "onlineSearch":
                                for i in data["content"]["details"]:
                                    if i["stage"] == "webSearchKeywords":
                                        web_search_content += i["title"] + ";"
                                        for j in i["content"]:
                                            web_search_content += j + ","
                                        web_search_content += "\n"
                                    else:
                                        web_search_content += i["title"] + ";" + i["content"] + "\n"
                            if current_event == "webSearch":
                                web_search_content += data["content"] + "\n"
                            if current_event == "webSearchDetail":
                                for i in data["content"]["details"]:
                                    index = i["index"]
                                    title = i["title"]
                                    url = i["url"]
                                    hostName = i["hostName"]
                                    summary = i["summary"]
                                    web_search_content += f"[{index}]"
                                    web_search_content += title + ";"
                                    web_search_content += url + ";"
                                    web_search_content += hostName + ";"
                                    web_search_content += summary + "\n"
                                    web_search_link_map[index] = url

                            # 处理消息事件
                            if current_event == "message":
                                result, in_thinking_block, thinking_started, is_first_chunk, thinking_content = await process_message_event(
                                    data, is_first_chunk, in_thinking_block, thinking_started, thinking_content, web_search_content, web_search_link_map
                                )
                                if result:
                                    yield result

                            # 处理生成结束事件
                            elif current_event == "generateEnd":
                                for chunk in process_generate_end_event(data, in_thinking_block, thinking_content):
                                    yield chunk

                        except json.JSONDecodeError as e:
                            logger.error(f"JSON解析错误: {e}")
                            continue

    except httpx.RequestError as e:
        logger.error(f"生成响应错误: {e}")
        # 尝试重新初始化会话
        try:
            session_manager.initialize()
            logger.info("会话已重新初始化")
        except Exception as re_init_error:
            logger.error(f"重新初始化会话失败: {re_init_error}")
        raise HTTPException(status_code=500, detail=f"请求错误: {str(e)}")


@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    current_time = int(time.time())
    models_data = [
        ModelData(
            id=Config.DEFAULT_MODEL,
            created=current_time,
            owned_by="wenxiaobai",
            root=Config.DEFAULT_MODEL,
            permission=[{
                "id": f"modelperm-{Config.DEFAULT_MODEL}",
                "object": "model_permission",
                "created": current_time,
                "allow_create_engine": False,
                "allow_sampling": True,
                "allow_logprobs": True,
                "allow_search_indices": False,
                "allow_view": True,
                "allow_fine_tuning": False,
                "organization": "wenxiaobai",
                "group": None,
                "is_blocking": False
            }]
        )
    ]

    return {"object": "list", "data": models_data}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, authorization: str = Header(None)):
    """处理聊天完成请求"""
    # 验证 API 密钥
    await verify_api_key(authorization)

    # 添加请求日志
    logger.info(f"Received chat request: model={request.model}, stream={request.stream}")

    messages = [msg.model_dump() for msg in request.messages]

    if not request.stream:
        # 非流式响应处理
        content = ""
        thinking_content = ""
        meta = None
        in_thinking = False

        async for chunk_str in generate_response(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                stream=True,  # 内部仍使用流式处理
                max_tokens=request.max_tokens,
                presence_penalty=request.presence_penalty,
                frequency_penalty=request.frequency_penalty,
                top_p=request.top_p
        ):
            try:
                if chunk_str.startswith("data: ") and not chunk_str.startswith("data: [DONE]"):
                    chunk = json.loads(chunk_str[len("data: "):])
                    if "choices" in chunk and chunk["choices"]:
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta:
                            content_part = delta["content"]

                            # 处理思考块标记
                            if content_part == "<think>__SESSION0xFE819635__\n\n":
                                in_thinking = True
                                continue
                            elif content_part == "\n</think>\n\n":
                                in_thinking = False
                                continue

                            # 收集内容
                            if in_thinking:
                                thinking_content += content_part
                            else:
                                content += content_part

                        # 收集元数据
                        if "meta" in delta:
                            meta = delta["meta"]
            except Exception as e:
                logger.error(f"处理非流式响应错误: {e}")

        # 构建完整响应
        return {
            "id": str(uuid.uuid4()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [{
                "message": {
                    "role": "assistant",
                    "reasoning_content": f"<think>__SESSION0xFE819635__\n{thinking_content}\n</think>" if thinking_content else None,
                    "content": content,
                    "meta": meta
                },
                "finish_reason": "stop"
            }]
        }

    # 流式响应
    return StreamingResponse(
        generate_response(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            stream=request.stream,
            max_tokens=request.max_tokens,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            top_p=request.top_p
        ),
        media_type="text/event-stream"
    )


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化会话"""
    try:
        session_manager.initialize()
    except Exception as e:
        logger.error(f"启动初始化错误: {e}")
        raise


@app.get("/health")
async def health_check():
    """健康检查端点"""
    if session_manager.is_initialized():
        return {"status": "ok", "session": "active"}
    else:
        return {"status": "degraded", "session": "inactive"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
