Thaumcraft Nexus 便携版

使用方式：
1. 程序会优先使用目标游戏进程自己的 Java，可兼容 Java 8 / 17 / 21 / 25。
2. 启动 GT New Horizons，进入游戏并打开神秘时代研究台。
3. 双击 ThaumcraftNexus.exe。
4. 在界面中读取当前笔记、自动放置，或使用轮椅模式批量处理。

Java 说明：
- Java 8 客户端需要可用的 Java 8 JDK，并且包含 lib\tools.jar。
- Java 17 到 Java 25 客户端需要带 jdk.attach 模块的 JDK/运行时。
- 如果自动识别失败，可以在 GUI 设置中刷新 JVM 列表并手动选择游戏进程。
- 如需随包携带 JDK，可放在 ThaumcraftNexus\jdk、ThaumcraftNexus\jdk21、ThaumcraftNexus\java21 等目录。

注意：
- 本工具是外部辅助程序，不需要把文件放进整合包 mods 目录。
- 运行时生成的 JSON、图片和设置会写入本目录下的 runtime 文件夹。
