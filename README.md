# 豆豆桌宠

使用 PySide6 制作的 Windows 透明桌面宠物。

## 使用方法

- 鼠标左键拖动：移动桌宠。
- 单击角色：依次触发跳跃、压扁回弹、左右抖动，并随机显示中文气泡。
- 鼠标滚轮：调整桌宠大小。
- 在其他窗口点击鼠标：切换到完整的“悬爪准备—自然按下鼠标—收爪”角色帧，不再拼接局部肢体。
- 连续敲键盘：使用两张完整角色姿态交替播放左右爪打字；程序只感应按键动作，不记录文字内容。
- 右键打开“键鼠统计”：默认查看今日，也可用日期选择器回看最近 365 天的每日数据，或切换到“累计”；全尺寸键盘热力图会显示每个按键的次数（左右 Ctrl、Shift、Alt 及主键盘/数字键盘 Enter 分开统计），同时展示鼠标左键、右键和滚轮点击次数。
- 空闲动作使用独立完整姿态，包括打哈欠、真实伸懒腰、左右张望和挥爪招呼。
- 右键的“空闲互动设置”可立即预览每个动作、选择启用哪些动作，并设置 5 秒到 5 分钟的等待时间。
- 右键的“编辑对话内容”可以按动作分类新增、修改或删除气泡文字，并可恢复内置对话；所有修改都会实时保存，关闭窗口时尚未提交的输入框文字也会自动加入。
- 鼠标右键还可选择预设大小、切换输入跟随、设置开机自动启动、切换始终置顶或退出程序。
- 程序只允许同时运行一个实例，重复启动时会弹窗提示。

默认推荐尺寸约为 `90×150`，适合放在电脑右下角；右键菜单提供 `110 / 130 / 150 / 180 / 220px` 五档高度。

双击 `dist\豆豆桌宠.exe` 即可运行，不需要目标电脑另装 Python。

位置、尺寸、空闲动作和自定义对话保存在 exe 同目录的 `豆豆桌宠配置.ini`。键鼠统计以稀疏数据保存在同目录的 `豆豆桌宠输入统计.json`，持续输入时仅更新内存，空闲或退出时才写盘；每日明细滚动保留今天及往前 364 天，过期明细删除后不会影响独立保存的累计数据。程序只记录按键标识和次数，不记录输入内容。只有开机自动启动功能使用当前用户的 Windows `Run` 注册表项。

## 从源码打包 Windows exe

下面的步骤适用于第一次下载源码、电脑上还没有项目环境的情况。打包过程只支持 Windows。

### 1. 安装 Python

本项目需要 **64 位 Python 3.8～3.11**，推荐使用 **Python 3.11**。当前依赖不支持 Python 3.12 及更高版本。

如果电脑尚未安装合适版本的 Python：

1. 打开 [Python 3.11.9 官方下载页面](https://www.python.org/downloads/release/python-3119/)。
2. 在页面底部的 **Files** 中下载 **Windows installer (64-bit)**。
3. 运行安装程序。
4. 安装界面底部务必勾选 **Add python.exe to PATH**。
5. 点击 **Install Now**。
6. 安装完成后，关闭并重新打开命令提示符。

> 本教程统一使用 `python` 命令，不要求电脑安装 `py` 启动器。

### 2. 下载并解压源码

可以使用以下任意一种方式获取源码：

- 在 GitHub Release 页面下载 `Source code (zip)`，然后完整解压。
- 使用 Git 克隆仓库：

```bat
git clone https://github.com/MuTongze/pets-desktop.git
```

不要直接在 ZIP 压缩包内运行脚本，必须先将整个源码目录解压出来。

### 3. 在源码目录打开命令提示符

1. 使用文件资源管理器进入解压后的源码目录。
2. 点击资源管理器顶部的地址栏。
3. 输入 `cmd` 后按回车。
4. 新打开的命令提示符应位于源码目录，并且当前目录中可以看到 `README.md`、`requirements.txt` 和 `build.ps1`。

可以运行以下命令确认：

```bat
dir
```

### 4. 检查 Python 版本

运行：

```bat
python --version
```

正确结果应为 Python 3.8～3.11，例如：

```text
Python 3.11.9
```

如果提示“`python` 不是内部或外部命令”，说明 Python 没有正确安装或没有加入 PATH。请重新执行第 1 步，并在安装后重新打开命令提示符。

如果显示 Python 3.12 或更高版本，请另外安装 Python 3.11，再继续下面的步骤。

### 5. 创建项目虚拟环境

在源码目录运行：

```bat
python -m venv .venv
```

命令正常完成时通常不会显示任何内容，源码目录中会新增一个 `.venv` 文件夹。

如果执行失败，不要继续后面的步骤，应先根据终端中显示的错误检查 Python 安装。

### 6. 安装打包依赖

依次运行：

```bat
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

安装依赖需要连接互联网。第二条命令执行完成后，应看到类似 `Successfully installed ...` 的提示。

### 7. 执行打包

运行：

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

脚本会使用项目内的 `.venv`、`requirements.txt` 和 `pet.spec` 进行单文件、无控制台打包。

打包成功后，可执行文件位于：

```text
dist\豆豆桌宠.exe
```

可以直接双击该文件进行测试，目标电脑不需要另外安装 Python。

### 后续重新打包

只要没有删除 `.venv`，以后修改代码后通常只需在源码目录重新运行：

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

如果修改了 `requirements.txt`，应先重新安装依赖：

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 常见问题

#### `'py' 不是内部或外部命令`

这是因为电脑没有安装 Python Launcher，不影响本项目。直接使用本文中的 `python` 命令即可。

#### `'python' 不是内部或外部命令`

Python 没有安装，或者安装时没有勾选 **Add python.exe to PATH**。重新安装 Python 3.11 并勾选该选项，然后关闭并重新打开命令提示符。

#### `Unknown option: -0`

`-0p` 是 `py` 启动器的参数，不能写成 `python -0p`。本项目不需要执行该命令，使用下面的命令检查版本即可：

```bat
python --version
```

#### 提示“未找到项目虚拟环境”

说明还没有创建 `.venv`，或者当前终端不在源码根目录。确认当前目录中存在 `build.ps1`，然后重新运行：

```bat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### 安装依赖时下载失败

先确认电脑能够正常访问互联网，然后重试：

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### PowerShell 显示中文乱码

这是 Windows PowerShell 5.1 读取 UTF-8 脚本时的显示问题，通常不影响命令执行。请优先查看错误信息中出现的文件路径、命令名称和退出码。
