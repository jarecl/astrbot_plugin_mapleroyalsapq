# -*- coding: utf-8 -*-
"""
MapleRoyals APQ 组队插件
用于 MapleRoyals 游戏中 APQ (Amoria Party Quest) 活动的组队管理

功能特性：
- 创建APQ组队活动
- 玩家报名加入
- 自动分配队伍
- 查询当前状态
- 管理员权限控制
- 数据持久化存储

作者：jarecl
版本：1.0.0
"""

import json           # JSON数据处理
import traceback      # 异常堆栈跟踪
import re             # 正则表达式，用于命令解析
from pathlib import Path    # 路径处理
from typing import Dict, List, Optional, Any, Tuple  # 类型提示

# AstrBot框架核心模块
from astrbot.api import AstrBotConfig, logger      # 配置和日志模块
from astrbot.api.event import AstrMessageEvent, filter  # 事件处理和过滤器
from astrbot.api.star import Context, Star, StarTools, register  # 插件核心框架


@register(
    "astrbot_plugin_mapleroyalsapq",  # 插件唯一标识符
    "jarecl",                         # 作者名
    "专用与mapleroyals这款游戏的APQ活动队员召集器",  # 插件描述
    "1.0.0",                          # 版本号
    "https://github.com/jarecl/astrbot_plugin_mapleroyalsapq"  # 仓库地址
)
class APQPlugin(Star):
    """APQ 组队插件主类
    
    继承自 Star 基类，实现 MapleRoyals 游戏中 APQ 活动的组队管理功能
    包含队伍创建、玩家报名、自动分配、状态查询等核心功能
    """

    # 类常量定义
    TEAM_SIZE = 6  # APQ 每队最多6人

    def __init__(self, context: Context, config: AstrBotConfig):
        """插件初始化方法
        
        Args:
            context: AstrBot 上下文对象
            config: 配置对象，包含管理员ID等配置信息
        """
        super().__init__(context)  # 调用父类初始化
        self.config = config       # 保存配置对象

        # 设置数据存储目录
        # 使用 StarTools 获取插件专用的数据目录
        self.data_dir = StarTools.get_data_dir("mapleroyalsapq")
        self.data_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在）
        self.database_path = self.data_dir / "database.json"  # 数据库文件路径

        # 初始化状态数据结构
        # 这是插件的核心数据结构，用于存储所有APQ活动状态
        self.state: Dict[str, Any] = {
            "status": "idle",      # 活动状态：idle(空闲)/recruiting(召集中)
            "captain": {},         # 队长信息
            "members": [],         # 参与者信息列表（包含队长，最多6人）
            "tracked_groups": [],  # 记录使用APQ命令的群聊ID列表（去重）
        }
        self._load_database()  # 从文件加载历史数据

    def _load_database(self) -> None:
        """从 database.json 加载数据
        
        在插件启动时调用，用于恢复上次运行时的数据状态
        如果文件不存在或格式错误，则使用默认的空状态
        """
        # 检查数据库文件是否存在
        if not self.database_path.exists():
            return  # 文件不存在，使用默认空状态

        try:
            # 读取并解析JSON文件
            data = json.loads(self.database_path.read_text(encoding="utf-8"))
            # 确保数据是字典格式
            if isinstance(data, dict):
                self.state.update(data)  # 更新状态数据
        except Exception as exc:
            # 记录加载错误
            logger.error("apq: load database failed: %s", exc)
            logger.error(traceback.format_exc())

    def _save_database(self) -> None:
        """将当前状态保存到 database.json
        
        每次状态变更后调用，确保数据持久化
        使用UTF-8编码和格式化输出，便于人工查看
        """
        try:
            # 将状态数据序列化为JSON格式并写入文件
            self.database_path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),  # ensure_ascii=False保持中文字符，indent=2格式化输出
                encoding="utf-8",  # 使用UTF-8编码
            )
        except Exception as exc:
            # 记录保存错误
            logger.error("apq: save database failed: %s", exc)
            logger.error(traceback.format_exc())

    def _get_sender_id(self, event: AstrMessageEvent) -> str:
        """获取消息发送者的唯一ID（QQ号）
        
        Args:
            event: 消息事件对象
        Returns:
            str: 发送者的QQ号字符串
        """
        return str(event.get_sender_id())

    def _get_sender_name(self, event: AstrMessageEvent) -> str:
        """获取消息发送者的显示名称

        Args:
            event: 消息事件对象
        Returns:
            str: 发送者的昵称或群名片
        """
        return str(event.get_sender_name())

    def _get_group_id(self, event: AstrMessageEvent) -> Optional[str]:
        """获取消息来源的群聊ID

        Args:
            event: 消息事件对象
        Returns:
            Optional[str]: 群聊的unified_msg_origin，如果不是群聊则返回None
        """
        # 通过检查 unified_msg_origin 是否包含群聊标识来判断
        unified_msg_origin = event.unified_msg_origin

        # 检查是否是群聊消息
        # unified_msg_origin 格式通常为: platform:GroupMessage:group_id
        if "GroupMessage" not in unified_msg_origin:
            # 如果没有GroupMessage标识，尝试从message_obj获取
            msg = getattr(event, "message_obj", None)
            if msg and hasattr(msg, "group_id"):
                group_id = getattr(msg, "group_id", None)
                if group_id:
                    # 构建完整的unified_msg_origin
                    if ":" in unified_msg_origin:
                        platform = unified_msg_origin.split(":")[0]
                        return f"{platform}:GroupMessage:{group_id}"
            return None

        return unified_msg_origin

    def _track_group_id(self, event: AstrMessageEvent) -> None:
        """记录使用APQ命令的群聊ID（去重）

        Args:
            event: 消息事件对象
        """
        group_id = self._get_group_id(event)
        if not group_id:
            return  # 不是群聊，不记录

        # 获取已记录的群聊列表，去重后保存
        tracked_groups = self.state.get("tracked_groups", [])
        if group_id not in tracked_groups:
            tracked_groups.append(group_id)
            self.state["tracked_groups"] = tracked_groups
            self._save_database()
            logger.info(f"apq: 新增记录群聊ID: {group_id}")

    async def _broadcast_to_all_groups(self, message: str) -> None:
        """广播消息到所有记录的群聊

        Args:
            message: 要发送的消息内容
        """
        tracked_groups = self.state.get("tracked_groups", [])
        if not tracked_groups:
            logger.warning("apq: 没有记录的群聊ID，无法广播")
            return

        success_count = 0
        for group_id in tracked_groups:
            try:
                await self.context.send_message(group_id, message)
                success_count += 1
                logger.info(f"apq: 广播消息到群聊 {group_id} 成功")
            except Exception as e:
                logger.error(f"apq: 广播消息到群聊 {group_id} 失败: {e}")

        logger.info(f"apq: 广播完成，成功 {success_count}/{len(tracked_groups)} 个群聊")

    def _is_super_admin(self, user_id: str) -> bool:
        """检查用户是否为超级管理员
        
        通过配置文件中的 admin_ids 判断用户权限
        
        Args:
            user_id: 用户QQ号字符串
        Returns:
            bool: True表示是超级管理员
        """
        # 从配置中获取管理员ID列表，如果不存在则返回空列表
        admin_ids = self.config.get("admin_ids", []) or []
        # 将所有ID转换为字符串格式统一比较
        admin_ids = [str(x) for x in admin_ids]
        return user_id in admin_ids

    def _is_group_admin(self, event: AstrMessageEvent) -> bool:
        """检查消息发送者是否为群组管理员
        
        通过多种方式检测用户在群内的管理权限
        支持不同平台的消息对象结构
        
        Args:
            event: 消息事件对象
        Returns:
            bool: True表示具有群管理权限
        """
        # 获取消息对象和发送者信息
        msg = getattr(event, "message_obj", None)
        sender = getattr(msg, "sender", None) if msg else None

        # 如果无法获取发送者信息，返回False
        if sender is None:
            return False

        # 检查直接的管理员属性
        if getattr(sender, "is_owner", False) or getattr(sender, "is_admin", False):
            return True

        # 检查角色属性
        role = getattr(sender, "role", "")
        if isinstance(role, str) and role.lower() in {"owner", "admin"}:
            return True

        # 检查权限属性
        permission = getattr(sender, "permission", "")
        if isinstance(permission, str) and permission.lower() in {"owner", "admin"}:
            return True

        return False

    def _has_admin_rights(self, event: AstrMessageEvent) -> bool:
        """检查用户是否具有管理员权限
        
        综合检查超级管理员和群管理员权限
        
        Args:
            event: 消息事件对象
        Returns:
            bool: True表示具有管理员权限
        """
        uid = self._get_sender_id(event)  # 获取用户QQ号
        # 用户具有任一管理员权限即可
        return self._is_super_admin(uid) or self._is_group_admin(event)

    def _remove_user_from_all(self, user_id: str) -> None:
        """从 members 中移除用户

        当用户重新报名或被管理员删除时调用
        确保用户数据的一致性

        Args:
            user_id: 要移除的用户QQ号
        """
        # 从成员列表中移除用户
        self.state["members"] = [p for p in self.state.get("members", []) if p.get("qq_number") != user_id]

    def _find_user_in_members(self, user_id: str) -> bool:
        """查找用户是否在成员列表中（通过QQ号）

        Args:
            user_id: 用户QQ号
        Returns:
            bool: True表示用户在成员列表中
        """
        for p in self.state.get("members", []):
            if p.get("qq_number") == user_id:
                return True
        return False

    def _find_player_by_character_id(self, char_id: str) -> Optional[Dict[str, Any]]:
        """通过角色ID查找玩家

        Args:
            char_id: 角色ID
        Returns:
            Optional[Dict[str, Any]]: 找到的玩家数据，未找到返回 None
        """
        char_id = char_id.strip()  # 清理空格

        # 在成员列表中查找
        for p in self.state.get("members", []):
            if p.get("character_id") == char_id:
                return p

        return None  # 未找到

    def _is_character_id_taken(self, char_id: str, exclude_user_id: str = None) -> bool:
        """检查角色ID是否已被使用

        Args:
            char_id: 角色ID
            exclude_user_id: 要排除的用户ID（用于更换角色时不和自己比较）
        Returns:
            bool: True表示角色ID已被使用
        """
        char_id = char_id.strip()  # 清理空格

        # 在成员列表中查找
        for p in self.state.get("members", []):
            # 如果角色ID相同，且不是当前用户（用于更换角色场景）
            if p.get("character_id") == char_id:
                if exclude_user_id is None or p.get("qq_number") != exclude_user_id:
                    return True

        return False

    def _format_player_info(self, player: Dict[str, Any]) -> str:
        """格式化玩家信息显示

        将玩家数据格式化为易读的字符串
        格式：[角色ID] 性别 职业 (QQ: QQ号)

        Args:
            player: 玩家数据字典
        Returns:
            str: 格式化后的玩家信息字符串
        """
        # 获取玩家各项信息，缺失时显示"?"
        char_id = player.get("character_id", "?")
        gender = player.get("gender", "?")
        job = player.get("job", "?")
        qq = player.get("qq_number", "?")

        # 返回格式化字符串（直接使用 br/gr）
        return f"[{char_id}] {gender} {job} (QQ: {qq})"

    def _parse_gender(self, gender: str) -> Optional[str]:
        """解析性别参数，支持中文和英文
        
        APQ游戏中只有两种性别：br(新娘) 和 gr(新郎)
        支持多种输入格式的兼容
        
        Args:
            gender: 性别参数字符串
        Returns:
            Optional[str]: 解析后的标准性别代码("br"/"gr")或None
        """
        gender = gender.strip().lower()  # 清理空格并转小写
        
        # 新娘相关输入映射到"br"
        if gender in ("br", "新娘"):
            return "br"
        # 新郎相关输入映射到"gr"
        elif gender in ("gr", "新郎"):
            return "gr"
        
        # 无效输入返回None
        return None

    def _validate_and_parse_join_command(self, content: str) -> Optional[Tuple[str, str, str]]:
        """
        验证并解析加入命令，严格验证格式防止信息错位

        严格的格式验证确保数据准确性，避免因格式错误导致的信息错位

        Args:
            content: 完整的命令字符串
        Returns:
            Optional[Tuple[str, str, str]]: (角色ID, 性别, 职业) 或 None

        格式要求: /加入APQ <角色ID> <br/gr/新郎/新娘> <职业>
        示例: /加入APQ dingzhen br 刀飞
        """
        # 注意：AstrBot框架的@filter.command装饰器已经移除了命令前缀
        # 这里只需要清理空格即可
        content = content.strip()

        # 使用正则表达式严格匹配格式
        # 模式说明：
        # ^\s*        - 开头可能有空格
        # (\S+)       - 第一组：非空白字符（角色ID），至少一个字符
        # \s+         - 必须有空格分隔
        # (br|gr|新郎|新娘) - 第二组：性别参数
        # \s+         - 必须有空格分隔
        # (\S+(?:\s+\S+)*) - 第三组：职业（可包含空格，由多个非空白字符组成）
        # \s*$        - 结尾可能有空格
        pattern = r'^\s*(\S+)\s+(br|gr|新郎|新娘)\s+(\S+(?:\s+\S+)*)\s*$'
        match = re.match(pattern, content, re.IGNORECASE)  # 忽略大小写匹配

        # 添加调试日志
        logger.info(f"apq: 解析加入命令 - 原始内容: {repr(content)}")
        logger.info(f"apq: 正则匹配结果: {match}")

        # 格式不匹配返回None
        if not match:
            return None

        # 提取各组匹配内容
        char_id = match.group(1).strip()      # 角色ID
        gender_raw = match.group(2).strip()   # 性别原始输入
        job = match.group(3).strip()          # 职业

        logger.info(f"apq: 解析结果 - char_id={repr(char_id)}, gender={repr(gender_raw)}, job={repr(job)}")

        # 验证职业不为空
        if not job:
            return None

        return (char_id, gender_raw, job)

    @filter.command("创建APQ")
    async def create_apq(self, event: AstrMessageEvent, char_id: str = "", gender: str = "", job: str = ""):
        """创建新的 APQ 组队会话并自动加入

        这是APQ活动的起点命令，创建新的组队会话并让创建者自动成为队长并加入

        Args:
            event: 消息事件对象
            char_id: 角色ID
            gender: 性别参数
            job: 职业
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 清理输入参数
        char_id = char_id.strip()
        gender_raw = gender.strip()
        job = job.strip()

        # 验证必需参数
        if not char_id or not gender_raw or not job:
            return event.plain_result("\n用法：/创建APQ <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/创建APQ dingzhen gr 拳手")

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("\n性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 获取用户基本信息
        uid = self._get_sender_id(event)    # QQ号
        name = self._get_sender_name(event) # 昵称

        # 检查是否已有进行中的APQ
        # 确保同一时间只有一个APQ活动进行
        if self.state.get("status") == "recruiting":
            members = self.state.get("members", [])
            if members:  # 如果有活动数据
                # 检查角色ID是否已被使用
                if self._is_character_id_taken(char_id):
                    return event.plain_result(f"\n有同名角色 [{char_id}] 已经参加，请使用其他角色名")
                return event.plain_result("\n目前已有APQ在召集，请等满员发车后再创建新的")

        # 设置活动状态为召集中
        self.state["status"] = "recruiting"

        # 创建玩家信息对象
        # 包含完整的玩家数据，用于后续处理和显示
        player_info = {
            "qq_number": uid,        # 用户QQ号（唯一标识）
            "nickname": name,        # 用户昵称
            "character_id": char_id, # 游戏角色ID
            "gender": gender,        # 性别（br/gr）
            "job": job,             # 职业
        }

        # 设置队长信息
        self.state["captain"] = player_info.copy()  # 使用副本避免共享引用

        # 将创建者加入成员列表（作为第一个成员）
        self.state["members"] = [player_info.copy()]  # 使用副本避免共享引用
        self._save_database()  # 保存到数据库

        # 返回成功消息（使用 br/gr）
        return event.plain_result(f"\nAPQ组队已创建！你已成为队长并加入：角色 {char_id}，{gender} {job}\n等待其他人加入...")

    @filter.command("加入APQ")
    async def join_apq(self, event: AstrMessageEvent, char_id: str = "", gender: str = "", job: str = ""):
        """
        加入 APQ 组队

        玩家使用此命令加入当前进行中的APQ活动
        使用正则表达式严格验证格式，防止信息错位
        当第6个人加入时，自动完成集结并重置数据

        Args:
            event: 消息事件对象
            char_id: 角色ID
            gender: 性别参数
            job: 职业
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 清理输入参数
        char_id = char_id.strip()
        gender_raw = gender.strip()
        job = job.strip()

        # 验证必需参数
        if not char_id or not gender_raw or not job:
            return event.plain_result("\n用法：/加入APQ <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/加入APQ 12345 br 刀飞")

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("\n性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 检查是否有APQ进行中
        if self.state.get("status") == "idle":
            return event.plain_result("\n目前没有进行中的APQ活动，请先创建APQ")

        # 获取用户基本信息
        uid = self._get_sender_id(event)    # QQ号
        name = self._get_sender_name(event) # 昵称

        # 检查角色ID是否已被使用
        if self._is_character_id_taken(char_id, exclude_user_id=uid):
            return event.plain_result(f"\n有同名角色 [{char_id}] 已经参加，请使用其他角色名")

        # 创建玩家信息对象
        player_info = {
            "qq_number": uid,        # 用户QQ号
            "nickname": name,        # 用户昵称
            "character_id": char_id, # 角色ID
            "gender": gender,        # 性别
            "job": job,             # 职业
        }

        # 移除用户之前的报名记录
        # 防止重复报名，确保数据一致性
        self._remove_user_from_all(uid)

        # 加入成员列表
        self.state.setdefault("members", []).append(player_info)
        self._save_database()  # 保存数据

        # 检查是否达到6人，如果达到则自动完成并重置
        members = self.state.get("members", [])
        if len(members) >= self.TEAM_SIZE:
            # 构建最终名单消息
            lines = ["=== APQ 集结完成 ===\n"]
            for idx, p in enumerate(members, 1):
                lines.append(f"{idx}. {self._format_player_info(p)}")

            # 计算统计信息
            br_count = sum(1 for p in members if p.get("gender") == "br")
            gr_count = sum(1 for p in members if p.get("gender") == "gr")
            lines.append(f"\n【统计】总人数：{len(members)}，br：{br_count}，gr：{gr_count}")

            final_message = "\n".join(lines) + "\n\nAPQ活动已结束，数据已清空，准备下一场活动！"

            # 广播消息到所有记录的群聊
            tracked_groups = self.state.get("tracked_groups", [])
            if tracked_groups:
                await self._broadcast_to_all_groups(final_message)

            # 重置database.json的数据（包括清空tracked_groups）
            self.state = {"status": "idle", "captain": {}, "members": [], "tracked_groups": []}
            self._save_database()

            # 返回完成消息
            return event.plain_result("\n" + final_message)

        # 返回成功消息和当前所有已参与的成员信息（使用 br/gr）

        # 构建当前成员列表
        lines = [f"已加入APQ！角色：{char_id}，{gender} {job}\n\n当前成员 ({len(members)}/{self.TEAM_SIZE})："]
        for idx, p in enumerate(members, 1):
            lines.append(f"{idx}. {self._format_player_info(p)}")

        return event.plain_result("\n" + "\n".join(lines))

    @filter.command("查询APQ")
    async def query_apq(self, event: AstrMessageEvent):
        """查询当前 APQ 组队状态

        显示完整的组队信息，包括队长和所有成员
        提供详细的统计信息

        Args:
            event: 消息事件对象
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 获取当前状态数据
        captain = self.state.get("captain", {})
        members = self.state.get("members", [])

        # 检查是否有活动进行中
        if not captain and not members:
            return event.plain_result("\n当前没有APQ组队，使用 /创建APQ 创建新的组队。")

        # 构建显示内容
        lines = ["=== APQ 组队状态 ==="]

        # 显示队长信息
        if captain:
            lines.append(f"\n【队长】")
            lines.append(f"  - {self._format_player_info(captain)}")

        # 显示成员列表
        if members:
            lines.append(f"\n【成员】({len(members)}/{self.TEAM_SIZE}人)")
            for idx, p in enumerate(members, 1):
                lines.append(f"{idx}. {self._format_player_info(p)}")

        # 计算统计信息
        br_count = sum(1 for p in members if p.get("gender") == "br")
        gr_count = sum(1 for p in members if p.get("gender") == "gr")

        # 添加统计信息
        lines.append(f"\n【统计】总人数：{len(members)}，br：{br_count}，gr：{gr_count}")

        # 返回格式化结果
        return event.plain_result("\n" + "\n".join(lines))

    @filter.command("我的APQ")
    async def my_apq(self, event: AstrMessageEvent):
        """查询自己的 APQ 报名状态

        让用户可以查看自己当前的报名信息，确认是否已成功加入
        这有助于解决用户"我刚报名怎么没了"的困惑

        Args:
            event: 消息事件对象
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 获取用户QQ号
        uid = self._get_sender_id(event)

        # 在成员列表中查找
        members = self.state.get("members", [])
        for idx, p in enumerate(members, 1):
            if p.get("qq_number") == uid:
                char_id = p.get("character_id", "?")
                gender = p.get("gender", "?")
                job = p.get("job", "?")
                is_captain = p.get("qq_number") == self.state.get("captain", {}).get("qq_number")
                role = "队长" if is_captain else "队员"
                return event.plain_result(f"\n你在APQ中（{role}）\n角色ID：{char_id}\n性别：{gender}\n职业：{job}\n当前人数：{len(members)}/{self.TEAM_SIZE}")

        # 未找到报名记录
        return event.plain_result("\n你还没有加入APQ组队。\n使用 /加入APQ <角色ID> <br/gr/新郎/新娘> <职业> 来加入组队")

    @filter.command("取消APQ")
    async def cancel_apq(self, event: AstrMessageEvent):
        """创建者取消自己的 APQ 活动，直接清空database.json的数据

        仅限APQ创建者使用，验证QQ号是否和队长的QQ号一致
        用于紧急情况下取消当前APQ活动，清空所有数据

        Args:
            event: 消息事件对象
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 获取用户ID
        uid = self._get_sender_id(event)

        # 获取队长信息
        captain = self.state.get("captain", {})

        # 检查是否有APQ进行中
        if not captain and not self.state.get("members"):
            return event.plain_result("\n当前没有APQ组队。")

        # 验证是否是队长（创建者）
        if captain.get("qq_number") != uid:
            return event.plain_result("\n只有APQ创建者才能取消活动。")

        # 清空database.json的数据
        # 直接重置为初始状态（包括清空tracked_groups）
        self.state = {"status": "idle", "captain": {}, "members": [], "tracked_groups": []}
        self._save_database()  # 保存清空后的状态

        return event.plain_result("\nAPQ活动已取消，数据已清空。")

    @filter.command("退出APQ")
    async def quit_apq(self, event: AstrMessageEvent):
        """退出 APQ 组队

        允许参与者退出当前进行中的APQ活动
        删除该QQ号对应的角色数据

        Args:
            event: 消息事件对象
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 获取用户ID
        uid = self._get_sender_id(event)

        # 获取队长信息
        captain = self.state.get("captain", {})

        # 检查是否有APQ进行中
        if self.state.get("status") == "idle" or not self.state.get("members"):
            return event.plain_result("\n当前没有APQ组队。")

        # 验证是否是队长
        if captain.get("qq_number") == uid:
            return event.plain_result("\n你是APQ创建者（队长），如需取消活动请使用 /取消APQ")

        # 检查用户是否在成员列表中
        is_member = self._find_user_in_members(uid)
        if not is_member:
            return event.plain_result("\n你还没有加入APQ组队。")

        # 移除用户
        self._remove_user_from_all(uid)
        self._save_database()  # 保存更新后的状态

        return event.plain_result("\n已退出APQ组队。")

    @filter.command("更换APQ角色")
    async def replace_apq(self, event: AstrMessageEvent, char_id: str = "", gender: str = "", job: str = ""):
        """更换角色信息

        允许玩家更新自己的报名信息，或管理员更新任意玩家信息

        Args:
            event: 消息事件对象
            char_id: 新的角色ID
            gender: 新的性别
            job: 新的职业
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 清理输入参数
        char_id = char_id.strip()
        gender_raw = gender.strip()
        job = job.strip()

        # 验证必需参数
        if not char_id or not gender_raw or not job:
            return event.plain_result("\n用法：/更换APQ角色 <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/更换APQ角色 dingzhen2 gr 拳手")

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("\n性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 获取用户ID
        uid = self._get_sender_id(event)

        # 检查是否是队长
        is_captain = self.state.get("captain", {}).get("qq_number") == uid

        # 在成员列表中查找用户记录
        found = False  # 标记是否找到用户记录
        for p in self.state.get("members", []):
            # 普通用户只能修改自己的信息
            if p.get("qq_number") == uid:
                p["character_id"] = char_id  # 更新角色ID
                p["gender"] = gender         # 更新性别
                p["job"] = job              # 更新职业
                found = True
                break

        # 如果是队长，同时更新队长信息
        if is_captain and found:
            self.state["captain"]["character_id"] = char_id
            self.state["captain"]["gender"] = gender
            self.state["captain"]["job"] = job

        # 如果未找到用户记录
        if not found:
            return event.plain_result("\n你还没有加入APQ组队。")

        self._save_database()  # 保存更新后的数据

        # 返回成功消息（使用 br/gr）
        return event.plain_result(f"\n已更新角色信息：角色 {char_id}，{gender} {job}")

    @filter.command("删除APQ角色")
    async def delete_apq_char(self, event: AstrMessageEvent, identifier: str = ""):
        """从APQ中删除指定角色（管理员）

        管理员专用命令，用于移除违规或不当报名的玩家
        支持通过QQ号或角色ID来查找并删除角色
        如果删除的角色是队长，则等同于重置APQ

        Args:
            event: 消息事件对象
            identifier: 要删除的角色ID或QQ号
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 检查管理员权限
        if not self._has_admin_rights(event):
            return event.plain_result("\n仅管理员可删除角色。")

        # 清理输入参数
        identifier = identifier.strip()

        # 验证参数
        if not identifier:
            return event.plain_result("\n用法：/删除APQ角色 <角色ID或QQ号>\n示例：/删除APQ角色 dingzhen 或 /删除APQ角色 123456789")

        # 先尝试通过角色ID查找玩家
        player = self._find_player_by_character_id(identifier)

        # 如果通过角色ID找不到，尝试通过QQ号查找
        if player is None:
            for p in self.state.get("members", []):
                if p.get("qq_number") == identifier:
                    player = p
                    break

        # 如果未找到玩家
        if player is None:
            return event.plain_result(f"\n未找到 {identifier} 对应的APQ记录（请检查角色ID或QQ号）。")

        # 获取玩家的QQ号、角色ID和昵称
        user_id = player.get("qq_number")
        char_id = player.get("character_id", identifier)
        player_name = player.get("nickname", user_id)

        # 检查该玩家是否是队长
        captain = self.state.get("captain", {})
        if captain.get("qq_number") == user_id:
            # 删除队长等同于重置APQ
            self.state = {"status": "idle", "captain": {}, "members": [], "tracked_groups": []}
            self._save_database()
            return event.plain_result(f"\n已将队长 {char_id}({player_name}) 删除，APQ已重置。")

        # 从成员列表中移除玩家
        self._remove_user_from_all(user_id)
        self._save_database()  # 保存更新后的状态

        return event.plain_result(f"\n已将角色 {char_id}({player_name}) 从APQ中移除。")

    @filter.command("重置APQ")
    async def reset_apq(self, event: AstrMessageEvent):
        """重置 APQ 组队数据（管理员）

        管理员专用命令，用于完全重置所有APQ数据
        慎用！会丢失所有当前活动数据

        Args:
            event: 消息事件对象
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 检查管理员权限
        if not self._has_admin_rights(event):
            return event.plain_result("\n仅管理员可重置APQ。")

        # 完全重置状态数据（包括清空tracked_groups）
        self.state = {"status": "idle", "captain": {}, "members": [], "tracked_groups": []}
        self._save_database()  # 保存重置后的状态

        return event.plain_result("\n已重置APQ组队数据。")

    @filter.command("APQ命令使用帮助")
    async def help_apq(self, event: AstrMessageEvent):
        """显示APQ插件的帮助信息

        根据用户权限显示不同的帮助内容
        管理员可以看到所有命令，普通用户只能看到用户命令
        """
        # 记录群聊ID
        self._track_group_id(event)

        # 基础帮助文本（所有用户可见）
        help_text = """=== APQ 命令使用帮助 ===

【用户命令】
/创建APQ <角色ID> <br/gr/新郎/新娘> <职业>
  创建一个新的 APQ 组队会话，并自动加入

/加入APQ <角色ID> <br/gr/新郎/新娘> <职业>
  加入现有的 APQ 组队

/查询APQ
  查询当前组队状态和参与者信息

/我的APQ
  查询自己的报名状态

/更换APQ角色 <角色ID> <br/gr/新郎/新娘> <职业>
  更新自己的角色信息

/退出APQ
  退出当前APQ组队

/取消APQ
  取消当前APQ活动（仅限创建者）

【参数说明】
- 角色ID: 游戏内角色唯一标识
- br/新娘: 表示新娘
- gr/新郎: 表示新郎
- 职业: 角色职业名称（没伤害就填小号）

【规则】
- 每队最多 6 人参与
- 同时只能有一个APQ活动处于召集中
- 第6个人加入后自动完成集结并重置数据"""

        # 如果是管理员，追加管理员命令部分
        if self._has_admin_rights(event):
            admin_text = """

【管理员命令】
/删除APQ角色 <角色ID或QQ号>
  从APQ中移除指定角色（支持角色ID或QQ号）
  如果删除的是队长，则等同于重置APQ

/重置APQ
  完全重置APQ数据"""
            help_text += admin_text

        return event.plain_result("\n" + help_text)

class Main(APQPlugin):
    """兼容旧版加载器
    
    为了兼容AstrBot的旧版本插件加载机制
    继承APQPlugin类，保持功能完整性和兼容性
    """
