# TSMC40 Spectre gm/ID 实践

此目录是 TSMC40 真实 PDK 的配置驱动 gm/ID 表征入口。PDK 模型不复制到本地
仓库；仿真在 `IC_Server` 上运行，并直接从 Spectre BSIM4 工作点读取 `Id`、
`gm`、`gds`、`Cgg`、`Cgd`、`Cgs`、`Vth` 和 `Vdsat`。

## 器件 Profile

[`profiles.json`](profiles.json) 保存所有工艺与扫描参数。当前内置：

| Profile | 器件 | W / L | VGS 扫描 | VDS 偏置 |
|---|---|---|---|---|
| `1v1` | `nch` / `pch` | 1 um / 40 nm | 0...1.1 V，5 mV | 0.05 / 0.55 / 1.10 V |
| `2v5` | `nch_25` / `pch_25` | 1 um / 270 nm | 0...2.5 V，10 mV | 0.10 / 1.25 / 2.50 V |

二者使用模型入口 `/PDKS/TSMC40nm/models/spectre/toplevel.scs` 和工艺角
`top_tt`。运行器根据 profile 动态生成网表，不再依赖手写的固定器件实例。

列出可用 profile：

```bash
./run_tsmc40.py --list-profiles
```

直接在远端运行：

```bash
ssh IC_Server
cd /home/userone/AAAIC/test_tb/gmid_tsmc40
./run_tsmc40.py --profile 1v1
./run_tsmc40.py --profile 2v5
```

从当前 Windows 项目部署并运行两套器件：

```powershell
pwsh .\practice\tsmc40_spectre\deploy_remote.ps1 -Run -Profiles '1v1,2v5'
```

部署脚本使用 SSH stdin 原子写入已授权目录，校验 SHA-256，并检查远端文件没有
`%TSD-Header-###%` 包装。可以先加 `-WhatIf` 检查目标。通用的单文件部署与策略
边界见 [`ssh-text-deploy`](../../ssh-text-deploy/SKILL.md) skill。

## 扩展与覆盖

新增器件族时，在 `profiles.json` 的 `profiles` 对象中增加一项即可。必须配置：

- PDK 模型入口和 corner；
- NMOS/PMOS Spectre 模型名；
- 绘制 W/L；
- VGS 起点、终点和步长；
- 一个或多个 VDS 幅值；
- gm/ID 绘图上限。

临时实验可用 CLI 覆盖 profile，而不修改 JSON：

```bash
./run_tsmc40.py --profile 2v5 --length-um 0.54 --vds 0.1,1.25,2.5
```

运行器会拒绝非法模型标识、非正尺寸、重复或越界的 VDS，以及不能整除扫描范围
的 VGS 步长。

## 输出

每套结果位于远端 `results/<profile>/`：

- `csv/tsmc40_gmid_all.csv`：全部曲线的合并查找表；
- `csv/tsmc40_<model>_vds_*.csv`：按器件和偏置拆分的数据；
- `plots/tsmc40_<model>_gmid.{png,svg}`：四面板曲线图；
- `summary.json`：实际配置与代表性工作点；
- `raw/characterize.scs`：本次运行生成的可复现网表；
- `raw/characterize.raw/` 和 `raw/spectre.log`：原始结果与日志。

`ft` 定义为 `gm/(2*pi*Cgg)`，`gm_ro` 定义为 `gm/gds`。PMOS 采用源极/体端
接地、栅漏施加负电压的等效偏置，表中电压和电流统一保存为幅值。结果是裸器件
前仿真数据，不包含版图扩散几何、LDE/WPE、失配或提取寄生。

服务器会对通过 `scp` 上传的 Python 源码做透明包装，因此仅通过项目部署脚本写入
已授权目录。网表、结果及 PDK 本体均保留在服务器上。
