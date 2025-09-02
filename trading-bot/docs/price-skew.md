# Price skew implementation details

**Inputs per cycle (e.g., every 200–500 ms or on ≥2-tick move):**

- `mid` = Binance ADAUSDT mid.
- `V_ADA = qty_ADA * mid`
- `V_USDM = qty_USDM`
- `V_total = max(V_ADA + V_USDM, ε)`

**Inventory imbalance (choose sign to match intent):**

```text
γ = clip( (V_USDM - V_ADA) / V_total , -γ_max, +γ_max )   # γ>0 ⇒ USDM-heavy (we want to buy ADA)
```

**Spreads (half-spreads in bps):**

```text
s_bid_bps = clamp( s_base_bps - λ*γ , s_min_bps , s_max_bps )   # tighten bids if γ>0
s_ask_bps = clamp( s_base_bps + λ*γ , s_min_bps , s_max_bps )   # widen asks  if γ>0
```

**Layer prices (linear depth for simplicity):**

```text
step_i_bps = i * depth_step_bps    # i = 0..(num_layers-1)

P_bid_i = round_tick( mid * (1 - (s_bid_bps + step_i_bps)/10_000) )
P_ask_i = round_tick( mid * (1 + (s_ask_bps + step_i_bps)/10_000) )
```

**Layer sizes (apply one knob, μ):**

```text
m_bid = clamp( 1 + μ*γ , m_min , m_max )   # bigger bids if γ>0
m_ask = clamp( 1 - μ*γ , m_min , m_max )   # smaller asks if γ>0

Q_bid_i = round_step( Q_base_i * m_bid )
Q_ask_i = round_step( Q_base_i * m_ask )
```

**Guards (keep simple):**

- Ensure `min_edge_bps = fees_bps + hedge_slippage_bps`; enforce `s_bid_bps, s_ask_bps ≥ min_edge_bps`.
- Cancel/replace only when any of: `|Δmid| ≥ 2 ticks`, `|Δγ| ≥ 0.02`, or `t ≥ reprice_ms`.

## Minimal params to expose

```yaml
s_base_bps: 3
λ: 10 # bps spread change per unit γ
μ: 0.8 # size multiplier per unit γ
γ_max: 0.5
s_min_bps: 2
s_max_bps: 50
depth_step_bps: 2
m_min: 0.3
m_max: 2.0
reprice_ms: 300
fees_bps: 1.5
hedge_slippage_bps: 2.0
```

## Example A — USDM-heavy (γ>0 ⇒ buy ADA)

### Inputs

- `mid` (Binance ADAUSDT): **0.5000**
- Balances: **qty_ADA=10,000**, **qty_USDM=7,000**
- Tick size: **0.0001** (round bids down, asks up)
- Step size (ADA): **1** (round sizes down)
- Layers: **5** with `Q_base_i = [100,150,200,250,300]` ADA
- Params:
  `s_base=3 bps`, `λ=10`, `μ=0.8`, `γ_max=0.5`, `s_min=2`, `s_max=50`,
  `depth_step=2 bps`, `m_min=0.3`, `m_max=2.0`,
  `fees=1.5 bps`, `hedge_slip=2.0 bps` → `min_edge=3.5 bps`

### Inventory imbalance

- `V_ADA = 10,000 * 0.50 = 5,000`, `V_USDM = 7,000`, `V_total = 12,000`
- `γ = (V_USDM − V_ADA)/V_total = (7000−5000)/12000 = **0.1667**` (within ±0.5)

### Half-spreads (after clamp + edge floor)

- Raw: `s_bid = 3 − 10*0.1667 = 1.33 → clamp→ 2`, edge floor → **3.5 bps**
- Raw: `s_ask = 3 + 10*0.1667 = **4.6667 bps**` (≥ edge)

### Size multipliers

- `m_bid = 1 + 0.8*0.1667 = **1.1333**` (bigger bids)
- `m_ask = 1 − 0.8*0.1667 = **0.8667**` (smaller asks)

### Quotes (i = 0..4, `step_i = i*2 bps`)

|   i | step_i (bps) |  P_bid_i   | Q_bid_i (ADA) |  P_ask_i   | Q_ask_i (ADA) |
| --: | :----------: | :--------: | :-----------: | :--------: | :-----------: |
|   0 |      0       | **0.4998** |    **113**    | **0.5003** |    **86**     |
|   1 |      2       |   0.4997   |      170      |   0.5004   |      130      |
|   2 |      4       |   0.4996   |      226      |   0.5005   |      173      |
|   3 |      6       |   0.4995   |      283      |   0.5006   |      216      |
|   4 |      8       |   0.4994   |      339      |   0.5007   |      260      |

_Computation notes_:

- `P_bid_i = round_down( mid * (1 − (s_bid + step_i)/10,000) )`
- `P_ask_i = round_up(   mid * (1 + (s_ask + step_i)/10,000) )`
- `Q_bid_i = round_step(Q_base_i * m_bid)`, `Q_ask_i = round_step(Q_base_i * m_ask)`

This shows the intended behavior: **bids are tighter & larger**, **asks wider & smaller** when you’re USDM-heavy.

---

## Example B — ADA-heavy (γ<0 ⇒ sell ADA)

Change only balances: **qty_ADA=15,000**, **qty_USDM=5,000**

- `V_ADA=7,500`, `V_USDM=5,000`, `V_total=12,500`, `γ = (5000−7500)/12500 = **−0.20**`
- Spreads (after floors): `s_bid=**5.0 bps**`, `s_ask=**3.5 bps**`
- Multipliers: `m_bid=**0.84**`, `m_ask=**1.16**`

|   i |  P_bid_i   | Q_bid_i |  P_ask_i   | Q_ask_i |
| --: | :--------: | :-----: | :--------: | :-----: |
|   0 | **0.4997** | **84**  | **0.5002** | **116** |
|   1 |   0.4996   |   126   |   0.5003   |   174   |
|   2 |   0.4995   |   168   |   0.5004   |   232   |
|   3 |   0.4994   |   210   |   0.5005   |   290   |
|   4 |   0.4993   |   252   |   0.5006   |   348   |

Here the **asks tighten & grow**, while **bids widen & shrink**, pushing flow to reduce the ADA surplus.

---

## Drop-in snippet (for your spec)

- **Imbalance**: `γ = clip((V_USDM − V_ADA)/V_total, −γ_max, +γ_max)`
- **Spreads**:
  `s_bid = max(clamp(s_base − λγ, s_min, s_max), min_edge)`
  `s_ask = max(clamp(s_base + λγ, s_min, s_max), min_edge)`
- **Prices**:
  `P_bid_i = floor_tick(mid * (1 − (s_bid + i·depth_step)/1e4))`
  `P_ask_i = ceil_tick( mid * (1 + (s_ask + i·depth_step)/1e4))`
- **Sizes**:
  `m_bid = clamp(1 + μγ, m_min, m_max)`
  `m_ask = clamp(1 − μγ, m_min, m_max)`
  `Q_bid_i = floor_step(Q_base_i · m_bid)`
  `Q_ask_i = floor_step(Q_base_i · m_ask)`
