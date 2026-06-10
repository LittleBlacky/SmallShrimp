"""共享测试数据集。所有 benchmark 从这里取数据。"""

# (layer, content)
MEMORIES = [
    ("profile", "用户叫 Zane"),
    ("profile", "偏好深色模式"),
    ("profile", "使用 Windows 系统"),
    ("facts", "项目使用 pytest 运行测试"),
    ("facts", "配置文件在 config/user.yaml"),
    ("facts", "Python 版本要求 >= 3.11"),
    ("projects", "后端服务端口 8000"),
    ("projects", "使用 SQLite 存储数据"),
    ("projects", "通过 pip install -e . 安装"),
    ("reflections", "read_file 前应先确认路径存在"),
    ("reflections", "shell 命令失败后检查退出码"),
    ("reflections", "gcc build failed with exit code 1"),
    ("facts", "用户偏好 async/await 风格"),
    ("facts", "使用 DeepSeek API"),
    ("reflections", "不要忽略 stderr 输出"),
]

# (query, expected_indices)
QUERIES = [
    ("测试怎么跑", {3}),
    ("端口是什么", {6}),
    ("编译失败了", {11}),
    ("怎么安装", {8}),
    ("用户叫什么", {0}),
    ("偏好什么", {1, 12}),
    ("配置文件在哪", {4}),
    ("上次读文件出错了", {9}),
    ("Python 版本要求", {5}),
    ("用的什么系统", {2}),
    ("stderr 的问题", {14}),
    ("用什么 API", {13}),
    ("数据库是什么", {7}),
    ("shell 失败了怎么办", {10}),
    ("偏好什么风格", {12}),
]
