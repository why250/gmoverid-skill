# 项目实践

这里是从仓库技能资产部署出的独立实践区，避免运行时日志、缓存和图表写回
`ngspice/`、`gmoverid/` 技能源目录。

## 一键运行

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\practice\run_practice.ps1
```

脚本依次完成：

1. 检查项目本地的 ngspice 47；
2. 运行 RC 充电瞬态仿真；
3. 生成 PTM 180 nm NMOS/PMOS 的 gm/ID、IV、电容及对比图；
4. 执行 gm/ID 数值自校验；
5. 在 `gm/ID = 15 V^-1`、`Id = 100 uA` 条件下反查 NMOS 宽度和工作点。

主要产物：

- `ngspice/plots/tran_rc_charging.png`
- `gmoverid/plots/180nm/*.png`
- `gmoverid/logs/practice_design.json`

仿真日志、缓存和图表由根目录 `.gitignore` 排除；实践脚本与说明可以纳入版本控制。

## Sky130A 真实 PDK

真实 Sky130A PDK 的 PVT/Monte Carlo 与 gm/ID 实践位于 `sky130/`：

```powershell
powershell -ExecutionPolicy Bypass -File .\practice\sky130\run_sky130_practice.ps1
```

详见 [`sky130/README.md`](sky130/README.md)。

## TSMC40 真实 PDK（远端 Spectre）

TSMC40 的配置驱动 gm/ID 实践位于 `tsmc40_spectre/`，内置 1.1 V
`nch/pch` 与 2.5 V `nch_25/pch_25` profile。PDK 和生成的数据保留在
`IC_Server:/home/userone/AAAIC/test_tb/gmid_tsmc40`，本地只保存配置与运行器。

详见 [`tsmc40_spectre/README.md`](tsmc40_spectre/README.md)。
