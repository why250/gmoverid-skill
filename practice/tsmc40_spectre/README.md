# TSMC40 Spectre gm/ID 实践

此目录是 TSMC40 真实 PDK 的 gm/ID 表征入口。PDK 模型不复制到本地仓库；
仿真在 `IC_Server_Local` 上运行，并直接从 Spectre BSIM4 工作点读取
`Id`、`gm`、`gds`、`Cgg`、`Cgd`、`Cgs`、`Vth` 和 `Vdsat`。

当前配置：

- 模型入口：`/PDKS/TSMC40nm/models/spectre/toplevel.scs`
- 工艺角：`top_tt`
- 器件：1.1 V standard-VT `nch` / `pch`
- 尺寸：`W=1 um`，绘制 `L=40 nm`
- 扫描：`|VGS|=0...1.1 V`，步长 `5 mV`
- 漏端偏置：`|VDS|=0.05 / 0.55 / 1.10 V`

远端运行：

```bash
ssh IC_Server_Local
cd /home/userone/AAAIC/test_tb/gmid_tsmc40
./run_tsmc40.py
```

从当前 Windows 项目重新部署并运行：

```powershell
.\practice\tsmc40_spectre\deploy_remote.ps1 -Run
```

部署脚本使用 SSH stdin 写入已授权目录，并在执行前验证远端 Python 文件
没有 `%TSD-Header-###%` 包装。可以先用 `-WhatIf` 检查目标。
通用的单文件部署、哈希校验和策略边界已整理到仓库的
[`ssh-text-deploy`](../../ssh-text-deploy/SKILL.md) skill；本目录脚本保留为
TSMC40 多文件部署的具体实例。

输出位于远端的 `results/`：

- `csv/tsmc40_gmid_all.csv`：六条曲线的合并查找表；
- `csv/tsmc40_{nch,pch}_vds_*.csv`：按器件和偏置拆分的数据；
- `plots/tsmc40_{nch,pch}_gmid.png`：四面板曲线图；
- `plots/tsmc40_{nch,pch}_gmid.svg`：对应矢量图；
- `summary.json`：配置与代表性工作点；
- `raw/`：Spectre PSFASCII 原始结果和日志。

`ft` 使用工作点定义 `gm/(2*pi*Cgg)`，`gm_ro` 使用 `gm/gds`。PMOS
采用源极/体端接地、栅漏施加负电压的等效偏置，输出表中电压和电流统一保存为幅值。

注意：该服务器会对通过 `scp` 上传的 Python 源码做透明加密，因此部署脚本通过
SSH 标准输入写入；当前远端目录已经部署为可直接执行的明文脚本。网表、结果及 PDK
本体均保留在服务器上。仅应对用户已授权且服务器策略允许的目标目录使用该方式。
