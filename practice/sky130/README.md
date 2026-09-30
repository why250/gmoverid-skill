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
4. 从 Sky130A 子电路内部 BSIM 器件直接读取 `gm`、`gds`、`Cgg`、`Vth`；
5. 生成 `sky130_fd_pr__nfet_01v8` 的多维 MOS 特性表和图册。

输出：

- `plots/gmoverid_sky130_nfet_01v8_L150nm.png`
- `data/sky130_gmid_<corner>.tsv`
- `data/sky130_gmid_summary.json`
- `smoke/mos_iv_summary.json`（机器安全策略会对 smoke 脚本同时生成的 CSV 做透明加密）

## 多维 MOS 特性表

`mos_characterization_sky130.py` 默认生成两个互补的数据 profile：

- `core`：在 TT、27 C 下扫描 `L × VDS × VBS × VGS`；
- `pvt`：在标称 `L=0.15 um、VDS=0.9 V、VBS=0 V` 下扫描
  `corner × temperature × VGS`。

默认采样范围：

```text
L           = 0.15, 0.30, 0.50, 1.00 um
VDS         = 0.10, 0.30, 0.60, 0.90, 1.20, 1.80 V
VBS         = 0, -0.30, -0.60 V
corner      = tt, ff, ss, fs, sf
temperature = -40, 27, 125 C
VGS         = 0 ... 1.8 V, step 10 mV
```

输出包括：

- `data/sky130_nfet_01v8_characterization.tsv`：所有 VGS 采样点的长表；
- `data/sky130_nfet_01v8_lookup.tsv`：在 gm/ID = 6/10/15/20 下插值后的设计表；
- `data/sky130_nfet_01v8_characterization.md`：标称工作点摘要；
- `plots/sky130_nfet_01v8_length_atlas.png`：沟道长度对比；
- `plots/sky130_nfet_01v8_bias_pvt_atlas.png`：VDS、VBS 和 PVT 对比。

主要列包含 `Id/W`、`gm/Id`、`gm/gds`、`fT`、`gmb/gm`、`Vth`、
`Vdsat`、`Cgg/Cgs/Cgd/Cgb/Cdb`。电容交叉项在 ngspice 内部采用带符号的
电荷导数约定；表中保存其绝对值，便于作为设计寄生量使用。
查表文件的 `available` 列表示目标 gm/ID 在该 PVT 条件下是否可达；例如高温
会降低弱反型的 gm/ID 理论上限，因此个别 125 C 条件无法达到 20 V^-1。

脚本会复用网表内容完全匹配的原始扫描数据；修改参数后会自动重新仿真。
如需无条件重跑，可添加 `--force-resim`。

默认的 `core + pvt` 避免第一次运行就产生庞大的五维笛卡尔积。如果确实需要
每一个 `corner × temperature × L × VDS × VBS` 组合，可单独运行：

```powershell
python .\practice\sky130\mos_characterization_sky130.py `
  --pdk-root D:\path\to\sky130A --full-cross
```

## 交互式 MOS Explorer

生成特性表后，启动本地静态服务器：

```powershell
.\practice\sky130\serve_mos_explorer.ps1
```

浏览器打开：

```text
http://localhost:8000/web/
```

网页直接读取 `data/sky130_nfet_01v8_characterization.tsv`，不需要数据库或
JavaScript 构建工具。主要功能：

- Explore：按 corner、温度、L、VDS、VBS 选择一个真实存在的仿真条件；
- Compare：沿 L、VDS、VBS、corner 或温度叠加比较；
- 在任意图表拖动 gm/ID 游标，四张曲线和工作点参数同步更新；
- 显示不可达 gm/ID，并支持复制工作点或导出当前曲线 TSV；
- 响应式布局、键盘操作和明暗主题。
