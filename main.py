from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image as MsgImage, Plain
import aiohttp
import base64
import asyncio
from io import BytesIO
from PIL import Image as PILImage

@register("animetrace", "deepseekR1", "动漫/Gal图片识别插件", "1.0.0")
class AnimeTracePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_url = "https://api.animetrace.com/v1/search"
        self.debug_mode = False  # 默认关闭调试模式

    async def initialize(self):
        """插件初始化"""
        logger.info("动漫/Gal识别插件已加载")

    @filter.command("anime", "动漫图片识别")
    async def anime_search(self, event: AstrMessageEvent):
        """
        识别动漫图片
        使用动画专用模型
        示例: /anime [图片]
        """
        async for result in self.process_image_recognition(event, "pre_stable"):
            yield result

    @filter.command("gal", "GalGame图片识别")
    async def gal_search(self, event: AstrMessageEvent):
        """
        识别GalGame图片
        使用Gal专用模型
        示例: /gal [图片]
        """
        async for result in self.process_image_recognition(event, "full_game_model_kira"):
            yield result

    async def process_image_recognition(self, event: AstrMessageEvent, model: str):
        """处理图片识别请求"""
        # 获取图片附件
        image_url = self.get_first_image_url(event.get_messages())
        if not image_url:
            yield event.plain_result("⚠️ 请发送一张图片")
            return
        
        # 调试信息
        if self.debug_mode:
            logger.info(f"开始识别: 模型={model}, 图片URL={image_url}")
        
        try:
            # 获取并处理图片
            img_data = await self.process_image(image_url)
            
            # 调用API
            results = await self.search_anime(img_data, model)
            
            # 检查API返回的数据
            if not results or not results.get("data") or not results["data"]:
                if self.debug_mode:
                    logger.warning(f"API返回空结果: {results}")
                yield event.plain_result("🔍 未识别到相关信息")
                return
                
            # 格式化响应
            response = self.format_response(results, model)
            yield event.plain_result(response)
            
        except asyncio.TimeoutError:
            yield event.plain_result("⏱️ 识别超时，请稍后重试")
        except Exception as e:
            logger.error(f"识别失败: {str(e)}")
            yield event.plain_result(f"❌ 识别失败: {str(e)}")

    def get_first_image_url(self, message_chain):
        """从消息链中获取第一张图片的URL"""
        for msg in message_chain:
            if isinstance(msg, MsgImage):
                if hasattr(msg, 'url') and msg.url:
                    return msg.url
                if hasattr(msg, 'data') and isinstance(msg.data, dict):
                    return msg.data.get('url', '')
        return ""

    async def process_image(self, img_url: str, max_size: int = 1024) -> str:
        """下载并优化图片"""
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as response:
                if response.status != 200:
                    raise Exception(f"图片下载失败: HTTP {response.status}")
                img_data = await response.read()
        
        img = PILImage.open(BytesIO(img_data))
        
        # 压缩大图
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, PILImage.LANCZOS)
        
        # 转换为Base64
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=85)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    async def search_anime(self, img_base64: str, model: str) -> dict:
        """调用AnimeTrace API"""
        payload = {
            "base64": img_base64,
            "is_multi": 1,  # 固定返回多个结果
            "model": model,
            "ai_detect": 1   # 固定开启AI检测
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url, 
                data=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API错误: {error_text[:100]}")
                
                return await response.json()

    def format_response(self, data: dict, model: str) -> str:
        """格式化API响应为消息"""
        # 检查API返回的数据结构
        if not data.get("data") or not data["data"]:
            return "🔍 未找到匹配的信息"
        
        # 获取第一个检测框的结果
        first_box = data["data"][0]
        characters = first_box.get("character", [])
        
        if not characters:
            return "🔍 未识别到具体角色信息"
        
        # 根据模型类型确定标题
        model_name = "动漫识别" if model == "pre_stable" else "Gal识别"
        emoji = "📺" if model == "pre_stable" else "🎮"
        
        # AI检测状态
        ai_status = data.get("ai", False)
        ai_flag = "🤖 AI生成" if ai_status else "NO AI"
        
        # 构建响应消息
        lines = [
            f"**{emoji} {model_name}结果** | {ai_flag}",
            "------------------------"
        ]
        
        # 处理结果 - 最多显示5个
        for i, item in enumerate(characters[:5]):
            character = item.get("character", "未知角色")
            anime = item.get("work", "未知作品")
            lines.append(f"{i+1}. **{character}** - 《{anime}》")
        
        # 添加数据来源
        if len(characters) > 5:
            lines.append(f"\n> 共找到 {len(characters)} 个结果，显示前5项")
        lines.append("\n数据来源: AnimeTrace，该结果仅供参考")
        
        return "\n".join(lines)

    async def terminate(self):
        """插件卸载时的清理工作"""
        logger.info("动漫/Gal识别插件已卸载")
