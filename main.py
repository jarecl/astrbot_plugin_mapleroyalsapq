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
import random         # 随机数生成，用于队伍分配
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
            "status": "idle",      # 活动状态：idle(空闲)/recruiting(召集中)/completed(已完成)
            "teams": {},           # 已分配的队伍字典，格式：{队伍名: [玩家列表]}
            "free": [],            # 自由报名池，存储还未分配队伍的玩家列表
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
        """从所有地方移除用户
        
        当用户重新报名或被管理员删除时调用
        确保用户数据的一致性
        
        Args:
            user_id: 要移除的用户QQ号
        """
        # 从自由报名池中移除
        # 检查用户是否在自由报名池中
        if user_id in [p.get("user_id") for p in self.state.get("free", [])]:
            # 过滤掉指定用户的记录
            self.state["free"] = [p for p in self.state.get("free", []) if p.get("user_id") != user_id]

        # 从所有队伍中移除
        teams = self.state.get("teams", {})  # 获取所有队伍
        for tname, members in list(teams.items()):  # 遍历所有队伍
            # 过滤掉指定用户的记录
            teams[tname] = [p for p in members if p.get("user_id") != user_id]
            # 如果队伍变空，删除该队伍
            if not teams[tname]:
                del teams[tname]

    def _find_user_team(self, user_id: str) -> Tuple[Optional[str], int]:
        """查找用户所在的队伍（通过QQ号）
        
        Args:
            user_id: 用户QQ号
        Returns:
            Tuple[Optional[str], int]: (队伍名, 队伍人数) 或 (None, 0)
        """
        teams = self.state.get("teams", {})  # 获取所有队伍

        # 遍历所有队伍查找用户
        for name, members in teams.items():
            for p in members:
                if p.get("user_id") == user_id:  # 找到匹配的用户
                    return name, len(members)   # 返回队伍名和人数

        return None, 0  # 未找到用户

    def _find_player_by_character_id(self, char_id: str) -> Tuple[Optional[str], Optional[str], int]:
        """通过角色ID查找玩家
        
        Args:
            char_id: 角色ID
        Returns:
            Tuple[Optional[str], Optional[str], int]: 
                (位置标识, 玩家对象引用, 队伍人数)
                位置标识：队伍名 或 "free" 或 None
                玩家对象：找到的玩家数据 或 None
                队伍人数：所在队伍的人数 或 0
        """
        teams = self.state.get("teams", {})  # 获取所有队伍
        char_id = char_id.strip()            # 清理空格

        # 在队伍中查找
        for name, members in teams.items():
            for p in members:
                if p.get("character_id") == char_id:  # 角色ID匹配
                    return name, p, len(members)     # 返回队伍信息

        # 在自由报名池中查找
        for p in self.state.get("free", []):
            if p.get("character_id") == char_id:     # 角色ID匹配
                return "free", p, 0                  # 返回自由池信息

        return None, None, 0  # 未找到

    def _assign_free(self) -> None:
        """为自由报名用户进行随机分队
        
        算法逻辑：
        1. 随机打乱自由报名用户顺序
        2. 优先填充现有队伍的空缺
        3. 为剩余用户创建新队伍
        4. 清空自由报名池
        """
        # 获取或初始化队伍字典
        teams = self.state.setdefault("teams", {})
        # 复制自由报名池（避免修改原列表）
        free = self.state.get("free", [])[:]

        # 打乱自由报名用户的顺序，确保随机性
        random.shuffle(free)

        # 优先填充现有队伍的空缺
        for name, members in list(teams.items()):  # 遍历现有队伍
            if not free:  # 如果没有剩余用户，结束
                break

            # 填充当前队伍到满员
            while len(members) < self.TEAM_SIZE and free:
                members.append(free.pop(0))  # 从自由池取出用户加入队伍
            teams[name] = members  # 更新队伍

        # 为剩余的自由用户创建新队伍
        idx = 1  # 队伍编号起始值
        while free:  # 还有剩余用户
            # 生成唯一队伍名
            team_name = f"队伍{idx}"
            while team_name in teams:  # 避免重复队伍名
                idx += 1
                team_name = f"队伍{idx}"

            # 创建新队伍（最多TEAM_SIZE人）
            teams[team_name] = free[:self.TEAM_SIZE]
            free = free[self.TEAM_SIZE:]  # 移除已分配的用户

        # 清空自由报名池
        self.state["free"] = []

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
        qq = player.get("user_id", "?")
        
        # 性别代码转换为中文显示
        gender_text = "新娘" if gender == "br" else "新郎" if gender == "gr" else gender
        
        # 返回格式化字符串
        return f"[{char_id}] {gender_text} {job} (QQ: {qq})"

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
        
        格式要求: /APQ加入 <角色ID> <br/gr/新郎/新娘> <职业>
        示例: /APQ加入 dingzhen br 刀飞
        """
        # 移除命令前缀，支持大小写
        content = content.replace("/APQ加入", "").replace("/apq加入", "").strip()

        # 使用正则表达式严格匹配格式
        # 模式说明：
        # ^\s*        - 开头可能有空格
        # (\S+?)      - 第一组：非空白字符（角色ID），非贪婪匹配
        # \s+         - 必须有空格分隔
        # (br|gr|新郎|新娘) - 第二组：性别参数
        # \s+         - 必须有空格分隔
        # (\S.*?)     - 第三组：职业（可包含空格）
        # \s*$        - 结尾可能有空格
        pattern = r'^\s*(\S+?)\s+(br|gr|新郎|新娘)\s+(\S.*?)\s*$'
        match = re.match(pattern, content, re.IGNORECASE)  # 忽略大小写匹配

        # 格式不匹配返回None
        if not match:
            return None

        # 提取各组匹配内容
        char_id = match.group(1).strip()      # 角色ID
        gender_raw = match.group(2).strip()   # 性别原始输入
        job = match.group(3).strip()          # 职业

        # 验证职业不为空
        if not job:
            return None

        return (char_id, gender_raw, job)

    @filter.command("创建APQ")
    async def create_apq(self, event: AstrMessageEvent, char_id: str = "", gender: str = "", job: str = ""):
        """创建新的 APQ 组队会话并自动加入
        
        这是APQ活动的起点命令，创建新的组队会话并让创建者自动加入
        
        Args:
            event: 消息事件对象
            char_id: 角色ID
            gender: 性别参数
            job: 职业
        """
        # 清理输入参数
        char_id = char_id.strip()
        gender_raw = gender.strip()
        job = job.strip()

        # 验证必需参数
        if not char_id or not gender_raw or not job:
            return event.plain_result("用法：/创建APQ <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/创建APQ dingzhen gr 拳手")

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 获取用户基本信息
        uid = self._get_sender_id(event)    # QQ号
        name = self._get_sender_name(event) # 昵称

        # 检查是否已有进行中的APQ
        # 确保同一时间只有一个APQ活动进行
        if self.state.get("status") == "recruiting":
            teams = self.state.get("teams", {})  # 已分配队伍
            free = self.state.get("free", [])    # 自由报名池
            if teams or free:  # 如果有活动数据
                return event.plain_result("当前已有APQ组队进行中，请先使用 /APQ取消 或 /APQ完成 结束当前活动。")

        # 设置活动状态为召集中
        self.state["status"] = "recruiting"

        # 创建玩家信息对象
        # 包含完整的玩家数据，用于后续处理和显示
        player_info = {
            "user_id": uid,           # 用户QQ号（唯一标识）
            "nickname": name,         # 用户昵称
            "character_id": char_id,  # 游戏角色ID
            "gender": gender,         # 性别（br/gr）
            "job": job,              # 职业
            # 在database.json存储时，默认要在最后加上用户的QQ号
            "qq_number": uid  # 这是为了确保QQ号被保存
        }

        # 将创建者加入自由报名池
        # 使用setdefault确保free键存在
        self.state.setdefault("free", []).append(player_info)
        self._save_database()  # 保存到数据库

        # 返回成功消息
        gender_text = '新娘' if gender == 'br' else '新郎'
        return event.plain_result(f"APQ组队已创建！你已加入：角色 {char_id}，{gender_text} {job}\n等待其他人加入...")

    @filter.command("APQ加入")
    async def join_apq(self, event: AstrMessageEvent):
        """
        加入 APQ 组队
        
        玩家使用此命令加入当前进行中的APQ活动
        使用正则表达式严格验证格式，防止信息错位
        
        Args:
            event: 消息事件对象
        """
        # 获取完整消息内容进行严格解析
        # 需要从原始消息对象中提取文本内容
        message_obj = getattr(event, "message_obj", None)
        if not message_obj:
            return event.plain_result("获取消息失败")

        message_text = getattr(message_obj, "message", [])
        if not isinstance(message_text, list):
            return event.plain_result("消息格式错误")

        # 提取纯文本内容
        # 处理可能的富文本消息格式
        full_text = ""
        for segment in message_text:
            if isinstance(segment, dict) and segment.get("type") == "text":
                full_text += segment.get("data", {}).get("text", "")

        # 验证并解析命令格式
        parsed = self._validate_and_parse_join_command(full_text)
        if not parsed:
            return event.plain_result("格式错误！用法：/APQ加入 <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/APQ加入 12345 br 刀飞")

        # 解包解析结果
        char_id, gender_raw, job = parsed

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 检查是否有APQ进行中
        if self.state.get("status") == "idle":
            return event.plain_result("当前没有APQ组队，请先使用 /创建APQ 创建组队。")

        # 获取用户基本信息
        uid = self._get_sender_id(event)    # QQ号
        name = self._get_sender_name(event) # 昵称

        # 创建玩家信息对象
        player_info = {
            "user_id": uid,           # 用户QQ号
            "nickname": name,         # 用户昵称
            "character_id": char_id,  # 角色ID
            "gender": gender,         # 性别
            "job": job,              # 职业
            "qq_number": uid  # 这是为了确保QQ号被保存
        }

        # 移除用户之前的报名记录
        # 防止重复报名，确保数据一致性
        self._remove_user_from_all(uid)

        # 加入自由报名池
        self.state.setdefault("free", []).append(player_info)
        self._save_database()  # 保存数据

        # 返回成功消息
        gender_text = '新娘' if gender == 'br' else '新郎'
        return event.plain_result(f"已加入APQ！角色：{char_id}，{gender_text} {job}\n等待分配队伍...")

    @filter.command("APQ查询")
    async def query_apq(self, event: AstrMessageEvent):
        """查询当前 APQ 组队状态
        
        显示完整的组队信息，包括已分配队伍和自由报名池
        提供详细的统计信息
        
        Args:
            event: 消息事件对象
        """
        # 获取当前状态数据
        teams = self.state.get("teams", {})  # 已分配队伍
        free = self.state.get("free", [])    # 自由报名池

        # 检查是否有活动进行中
        if not teams and not free:
            return event.plain_result("当前没有APQ组队，使用 /创建APQ 创建新的组队。")

        # 构建显示内容
        lines = ["=== APQ 组队状态 ==="]

        # 显示已分配的队伍信息
        if teams:
            lines.append("\n【已分配队伍】")
            for name, members in teams.items():
                # 显示队伍名称和人数
                lines.append(f"\n队伍 {name} ({len(members)}/{self.TEAM_SIZE}人)：")
                # 显示每个成员的详细信息
                for p in members:
                    lines.append(f"  - {self._format_player_info(p)}")

        # 显示自由报名池
        if free:
            lines.append("\n【自由报名池】")
            for p in free:
                lines.append(f"  - {self._format_player_info(p)}")

        # 计算统计信息
        total_players = sum(len(m) for m in teams.values()) + len(free)  # 总人数
        # 新娘人数统计（队伍中+自由池中）
        br_count = sum(1 for m in teams.values() for p in m if p.get("gender") == "br") + \
                   sum(1 for p in free if p.get("gender") == "br")
        # 新郎人数统计
        gr_count = sum(1 for m in teams.values() for p in m if p.get("gender") == "gr") + \
                   sum(1 for p in free if p.get("gender") == "gr")

        # 添加统计信息
        lines.append(f"\n【统计】总人数：{total_players}，新娘：{br_count}，新郎：{gr_count}")

        # 返回格式化结果
        return event.plain_result("\n".join(lines))

    @filter.command("APQ完成")
    async def finish_apq(self, event: AstrMessageEvent):
        """完成集结，显示最终队伍分配，并清空database.json的数据
        
        此命令用于结束当前APQ活动，自动分配剩余的自由报名玩家
        并显示最终的队伍分配结果
        
        Args:
            event: 消息事件对象
        """
        # 获取当前状态
        teams = self.state.get("teams", {})
        free = self.state.get("free", [])

        # 检查是否有活动进行中
        if not teams and not free:
            return event.plain_result("当前没有APQ组队，使用 /创建APQ 创建新的组队。")

        # 为自由报名玩家分配队伍
        # 确保所有报名玩家都被分配到队伍中
        if free:
            self._assign_free()  # 执行自动分队算法
            self._save_database()  # 保存分配结果

        # 显示最终结果
        teams = self.state.get("teams", {})  # 获取更新后的队伍信息
        lines = ["=== APQ 集结完成 ===\n"]

        # 显示每个队伍的最终成员
        for name, members in teams.items():
            lines.append(f"\n队伍 {name} ({len(members)}/{self.TEAM_SIZE}人)：")
            for p in members:
                lines.append(f"  - {self._format_player_info(p)}")

        # 计算最终统计信息
        total_players = sum(len(m) for m in teams.values())  # 总人数
        br_count = sum(1 for m in teams.values() for p in m if p.get("gender") == "br")  # 新娘数
        gr_count = sum(1 for m in teams.values() for p in m if p.get("gender") == "gr")  # 新郎数

        # 添加统计信息
        lines.append(f"\n【统计】共 {len(teams)} 个队伍，总人数：{total_players}，新娘：{br_count}，新郎：{gr_count}")

        # 清空database.json的数据，以准备下一场APQ活动
        # 重置为初始状态
        self.state = {"status": "idle", "teams": {}, "free": []}
        self._save_database()  # 保存清空后的状态

        # 返回完成消息
        return event.plain_result("\n".join(lines) + "\n\nAPQ活动已结束，数据已清空，准备下一场活动！")

    @filter.command("APQ取消")
    async def cancel_apq(self, event: AstrMessageEvent):
        """创建者取消自己的 APQ 活动，直接清空database.json的数据
        
        用于紧急情况下取消当前APQ活动，清空所有数据
        
        Args:
            event: 消息事件对象
        """
        # 获取用户ID（用于权限检查，虽然当前未使用）
        uid = self._get_sender_id(event)

        # 检查是否有APQ进行中
        teams = self.state.get("teams", {})  # 已分配队伍
        free = self.state.get("free", [])    # 自由报名池

        # 如果没有活动数据
        if not teams and not free:
            return event.plain_result("当前没有APQ组队。")

        # 清空database.json的数据
        # 直接重置为初始状态
        self.state = {"status": "idle", "teams": {}, "free": []}
        self._save_database()  # 保存清空后的状态

        return event.plain_result("APQ活动已取消，数据已清空。")

    @filter.command("APQ更换")
    async def replace_apq(self, event: AstrMessageEvent, char_id: str = "", gender: str = "", job: str = ""):
        """更换角色信息
        
        允许玩家更新自己的报名信息，或管理员更新任意玩家信息
        
        Args:
            event: 消息事件对象
            char_id: 新的角色ID
            gender: 新的性别
            job: 新的职业
        """
        # 清理输入参数
        char_id = char_id.strip()
        gender_raw = gender.strip()
        job = job.strip()

        # 验证必需参数
        if not char_id or not gender_raw or not job:
            return event.plain_result("用法：/APQ更换 <角色ID> <br/gr/新郎/新娘> <职业>\n示例：/APQ更换 dingzhen2 gr 拳手")

        # 解析性别参数为标准格式
        gender = self._parse_gender(gender_raw)
        if not gender:
            return event.plain_result("性别参数错误，必须是 br/新娘 或 gr/新郎")

        # 获取用户ID
        uid = self._get_sender_id(event)

        # 查找并更新用户记录
        found = False  # 标记是否找到用户记录
        teams = self.state.get("teams", {})  # 获取队伍数据

        # 检查是否有管理员权限
        is_admin = self._has_admin_rights(event)

        # 在队伍中查找用户记录
        for name, members in list(teams.items()):
            for p in members:
                # 普通用户只能修改自己的信息，管理员可以修改任何人的信息
                if p.get("user_id") == uid or is_admin:
                    p["character_id"] = char_id  # 更新角色ID
                    p["gender"] = gender         # 更新性别
                    p["job"] = job              # 更新职业
                    found = True
                    break
            if found:
                break

        # 在自由报名池中查找
        if not found:
            for p in self.state.get("free", []):
                if p.get("user_id") == uid or is_admin:
                    p["character_id"] = char_id
                    p["gender"] = gender
                    p["job"] = job
                    found = True
                    break

        # 如果未找到用户记录
        if not found:
            return event.plain_result("你还没有加入APQ组队。")

        self._save_database()  # 保存更新后的数据
        
        # 返回成功消息
        gender_text = '新娘' if gender == 'br' else '新郎'
        return event.plain_result(f"已更新角色信息：角色 {char_id}，{gender_text} {job}")

    @filter.command("APQ删除")
    async def delete_apq(self, event: AstrMessageEvent, char_id: str = ""):
        """从APQ中删除指定角色（管理员）
        
        管理员专用命令，用于移除违规或不当报名的玩家
        
        Args:
            event: 消息事件对象
            char_id: 要删除的角色ID
        """
        # 检查管理员权限
        if not self._has_admin_rights(event):
            return event.plain_result("仅管理员可删除角色。")

        # 清理输入参数
        char_id = char_id.strip()

        # 验证参数
        if not char_id:
            return event.plain_result("用法：/APQ删除 <角色ID>\n示例：/APQ删除 dingzhen")

        # 通过角色ID查找玩家
        location, player, _ = self._find_player_by_character_id(char_id)

        # 如果未找到玩家
        if location is None:
            return event.plain_result(f"未找到角色 {char_id} 的APQ记录。")

        # 获取玩家的QQ号和昵称
        user_id = player.get("user_id")
        player_name = player.get("nickname", user_id)

        # 从所有地方移除玩家
        self._remove_user_from_all(user_id)
        self._save_database()  # 保存更新后的状态

        return event.plain_result(f"已将角色 {char_id}({player_name}) 从APQ中移除。")

    @filter.command("APQ重置")
    async def reset_apq(self, event: AstrMessageEvent):
        """重置 APQ 组队数据（管理员）
        
        管理员专用命令，用于完全重置所有APQ数据
        慎用！会丢失所有当前活动数据
        
        Args:
            event: 消息事件对象
        """
        # 检查管理员权限
        if not self._has_admin_rights(event):
            return event.plain_result("仅管理员可重置APQ。")

        # 完全重置状态数据
        self.state = {"status": "idle", "teams": {}, "free": []}
        self._save_database()  # 保存重置后的状态

        return event.plain_result("已重置APQ组队数据。")


class Main(APQPlugin):
    """兼容旧版加载器
    
    为了兼容AstrBot的旧版本插件加载机制
    继承APQPlugin类，保持功能完整性和兼容性
    """
