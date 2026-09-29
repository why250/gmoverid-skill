# Sky130A gm/ID 实践

该目录使用真实 Sky130A PDK 的 `sky130_fd_pr__nfet_01v8` 器件，而不是 PTM
预测模型。当前锁定的 open_pdks/Volare 版本为：

```text
c6d73a35f524070e85faff4a6a9eef49553ebc2b
```

运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\practice\sky130\run_sky130_practice.ps1
```

如果 PDK 安装在其他位置：

```powershell
.\practice\sky130\run_sky130_practice.ps1 -PdkRoot D:\path\to\sky130A
```

流程包括：

1. 五个工艺角 `tt/ff/ss/fs/sf` 的 NMOS Id-Vgs smoke test；
2. 三次 process Monte Carlo smoke test；
3. 五个工艺角的 gm/ID 扫描和曲线生成；
4. 从 Sky130A 子电路内部 BSIM 器件直接读取 `gm`、`gds`、`Cgg`、`Vth`。

输出：

- `plots/gmoverid_sky130_nfet_01v8_L150nm.png`
- `data/sky130_gmid_<corner>.tsv`
- `data/sky130_gmid_summary.json`
- `smoke/mos_iv_summary.json`（机器安全策略会对 smoke 脚本同时生成的 CSV 做透明加密）
