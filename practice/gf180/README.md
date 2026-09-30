# GF180MCU BJT 性能图谱

使用 GF180MCU 官方 `sm141064.ngspice` 模型，扫描垂直 NPN 的基极偏压，在固定
`VCE` 下按发射极面积计算 `Jc = Ic/Ae`。输出每个器件的 CSV、汇总 JSON 和四幅曲线：
`gm/Ic`、直流电流增益 `beta`、模型内部的 `gm/go`、以及 `(Cpi+Cmu)/Ae`。

## 运行

在仓库根目录执行：

```powershell
python .\practice\gf180\bjt_characterization_gf180.py
```

首次运行会下载固定提交 `9f992d5a9186d1f7820c58f039c484ad35b2edea` 的
[GF180MCU 官方 ngspice 模型](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_pr/blob/9f992d5a9186d1f7820c58f039c484ad35b2edea/models/ngspice/sm141064.ngspice)
至 `models/`。已有 GF180MCU PDK 时，可指定模型文件或 PDK 根目录：

```powershell
python .\practice\gf180\bjt_characterization_gf180.py --model-lib C:\path\to\gf180mcuC --corner bjt_typical
```

需要 Python、NumPy、Matplotlib 和 ngspice。脚本优先使用仓库本地的
`.claude/tools/Spice64/bin/ngspice_con.exe`，也可用 `--ngspice` 指定程序。
`--devices` 可选择官方模型中的六种垂直 NPN 尺寸；默认选
`0.54 × 2`、`0.54 × 4`、`0.54 × 8 µm²`。`--corner` 支持
`bjt_typical`、`bjt_ff`、`bjt_ss`，并可调整温度和 `VCE`。

图保存在 `plots/`，逐点数据保存在 `data/`，网表和仿真日志保存在 `logs/`。
`data/bjt_summary.json` 记录模型路径和 SHA-256，便于复现。

## 指标边界

- `gm`、`go`、`Cpi`、`Cmu` 读取自 BJT 模型内部的 ngspice 工作点参数；
  `Ic`、`Ib` 则从端口电流取得。因此 `gm/go` 是模型内部指标，未把外部
  基极、发射极和集电极串联电阻折算进去。
- 这组公开的 GF180MCU NPN 模型卡没有指定前向渡越时间 `TF`。
  因而不绘制 `fT`：用 `gm/(2π(Cpi+Cmu))` 算出的数值不应当作实际截止频率。
- 电流密度图只是模型预测。使用前仍需核对目标偏置、电压、温度、版图
  和模型相关性。官方[器件清单](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_5.html)
  列出了各个实际发射极尺寸。

## InP HBT 资料

[Q. Liu 的博士论文，第 2.3 表](https://seabaugh.nd.edu/assets/348687/d01qingminliuphddissertation2006.pdf)
公开了一颗 `1 µm²` InP HBT 的 Gummel–Poon SPICE 参数，可用于教学或
该器件的对比仿真。这是一组特定器件的研究参数，并非具有工艺角、版图规则和
多尺寸模型的完整开放 InP PDK。
