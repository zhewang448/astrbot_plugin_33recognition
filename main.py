import shutil
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.api.message_components import ComponentType  # 判断文件类型

DEFAAULT_SYSTEM_PROMPT_1 = "如果我发的图片中有关键词或者其他与其发音相似的中文词语，那么你就返回哈基米，除此之外不用返回别的东西。若没有则返回未发现关键词。例子：若关键词为33的时候，'珊珊'或者'山山'也需要返回哈基米"
DEFAAULT_SYSTEM_PROMPT_2 = "如果我发的图片中有关键词列表中的词，那么你就返回哈基米，除此之外不用返回别的东西。若没有则返回未发现关键词。"


@register(
    "astrbot_plugin_33recognition",
    "bushikq",
    "一个调用大模型检测图片中关键词的astrbot插件",
    "1.3.4",
)
class Recognition33Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_33recognition"))
        self.config = config

        ##处理检测文本
        self.input_config = self.config.get("input_config")
        # 关键词
        self.important_word_list = self.input_config.get("important_word_list", [])
        # 是否启用谐音模式
        self.xieyin_mode_on = self.input_config.get("xieyin_mode_on", True)
        # 自定义回复内容
        self.reply_config = self.config.get("reply_config")
        self.reply_text = self.reply_config.get("reply_text", "nybb")
        self.at_on = self.reply_config.get("at_on", True)
        self.reply_image_list = self.reply_config.get("reply_image_list", ["nybb.jpg"])
        logger.debug(f"reply_image_list: {self.reply_image_list}")
        ## 处理黑白名单
        self.black_white_list_config = self.config.get("black_white_list_config")
        self.white_list_on = self.black_white_list_config.get("white_list_on", False)
        self.white_list = self.black_white_list_config.get("white_list", [])
        self.black_list_on = self.black_white_list_config.get("black_list_on", False)
        self.black_list = self.black_white_list_config.get("black_list", [])

        # 处理是否需要自定义图片转述模型
        self.default_image_caption_provider_id = self.config.get(
            "default_image_caption_provider_id", None
        )

        # 处理图片目录
        self.handle_image_dir()
        # 处理prompt
        self.handle_prompt()

    def handle_prompt(self):
        if self.xieyin_mode_on:
            self.prompt = DEFAAULT_SYSTEM_PROMPT_1
        else:
            self.prompt = DEFAAULT_SYSTEM_PROMPT_2

    def handle_image_dir(self):
        if not Path(self.data_dir / "nybb.jpg").exists():
            if Path(self.plugin_dir / "nybb.jpg").exists():
                # 复制 nybb.jpg 到 data_dir
                shutil.copy(self.plugin_dir / "nybb.jpg", self.data_dir / "nybb.jpg")
            else:
                logger.warning("nybb.jpg文件缺失")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def monitor_imporant_word(self, event: AstrMessageEvent):
        if not self.important_word_list:
            logger.error("你没有设置关键词，不执行图片关键词检测呦~")
            return
        only_id = event.session_id.rsplit("_", 1)[-1]
        if not await self.handle_group(only_id):
            return

        raw_msg = event.message_obj.message
        logger.debug(f"raw_msg: {raw_msg}")
        pic_url_list = []
        for image in raw_msg:
            if image.type == ComponentType.Image:
                if hasattr(image, "url"):
                    if image.url:
                        pic_url_list.append(image.url)
                    elif hasattr(image, "file"):
                        if image.file:
                            pic_url_list.append(image.file)
        if not pic_url_list:
            return
        logger.debug(f"pic_url_list: {pic_url_list}")
        if self.default_image_caption_provider_id:
            prov = self.context.get_provider_by_id(
                self.default_image_caption_provider_id
            )
            logger.debug(f"使用配置的图片转述模型: {prov}")
        else:
            prov = self.context.get_using_provider(umo=event.unified_msg_origin)
        if prov:
            llm_resp = await prov.text_chat(
                prompt=f"{self.prompt}, 关键词列表为{self.important_word_list}",
                image_urls=pic_url_list,
                system_prompt="严格执行我的命令",
            )
            logger.debug(f"llm_resp: {llm_resp}")
            if "哈基米" in str(llm_resp.result_chain):
                logger.info("发现33")
                # 可自定义回复文本
                msg_components = [Comp.Plain(text=self.reply_text)]
                msg_components.append(
                    Comp.At(qq=event.get_sender_id())
                ) if self.at_on else None

                if self.reply_image_list:
                    for reply_image_name in self.reply_image_list:
                        msg_components.append(
                            Comp.Image.fromFileSystem(
                                f"{self.data_dir}/{reply_image_name}"
                            )
                        )
                yield event.chain_result(msg_components)
            else:
                logger.debug(f"未发现{self.important_word_list}")
        else:
            logger.error("未匹配到provider") if not prov else None

    async def handle_group(self, session_id):
        if self.white_list_on and self.white_list:
            return session_id in self.white_list
        elif self.black_list_on and self.black_list:
            return session_id not in self.black_list
        elif not self.white_list_on and not self.black_list_on:
            return True
        else:
            logger.warning("白名单或黑名单设置不当，默认不限制")
            return True
