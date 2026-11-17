import json, sys, numpy as np, datetime as dt
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib import font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
plt.rcParams["font.family"]="WenQuanYi Zen Hei"
d=json.load(open(sys.argv[1])); out=sys.argv[2]
c=sorted(d["candles"],key=lambda r:int(r[0])); o={int(r[0]):float(r[2]) for r in d["oi"]}
ts=np.array([int(r[0]) for r in c]); hi=np.array([float(r[2]) for r in c]); lo=np.array([float(r[3]) for r in c]); cl=np.array([float(r[4]) for r in c])
tp=(hi+lo+cl)/3
oib=np.array([o.get(t,np.nan) for t in ts]); 
for i in range(1,len(oib)):
    if np.isnan(oib[i]): oib[i]=oib[i-1]
LEV={3:.04,5:.08,10:.16,15:.10,20:.14,25:.12,30:.08,40:.07,50:.10,75:.05,100:.06}; MM=0.005
P=cl[-1]; lo_b,hi_b=P*0.85,P*1.17; step=250
bins=np.arange(np.floor(lo_b/step)*step,hi_b+step,step); nb=len(bins)-1
pos=[]  # [liq_price, side(+1 long), btc]
H=len(ts); M=np.zeros((nb,H))
for t in range(1,H):
    # liquidations this hour
    pos=[p for p in pos if not ((p[1]>0 and lo[t]<=p[0]) or (p[1]<0 and hi[t]>=p[0]))]
    dlt=oib[t]-oib[t-1]
    if dlt>0:
        for L,w in LEV.items():
            pos.append([tp[t]*(1-1/L+MM),1,dlt*w/2]); pos.append([tp[t]*(1+1/L-MM),-1,dlt*w/2])
    elif dlt<0 and pos:
        tot=sum(p[2] for p in pos)/2
        f=max(0,1-(-dlt)/tot) if tot>0 else 0
        for p in pos: p[2]*=f
    if pos:
        a=np.array(pos); usd=a[:,2]*P
        M[:,t]=np.histogram(a[:,0],bins=bins,weights=usd)[0]
a=np.array(pos)
show=24*14; s0=H-show
times=[dt.datetime.fromtimestamp(x/1000,dt.UTC).replace(tzinfo=None)+dt.timedelta(hours=8) for x in ts]
seq=["#fcfcfb","#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95","#0d366b"]
cmap=LinearSegmentedColormap.from_list("seq",seq)
fig=plt.figure(figsize=(13,7.2),facecolor="#fcfcfb")
gs=fig.add_gridspec(2,2,width_ratios=[4.2,1],height_ratios=[24,1],wspace=0.04,hspace=0.28)
ax=fig.add_subplot(gs[0,0]); ax2=fig.add_subplot(gs[0,1],sharey=ax); cax=fig.add_subplot(gs[1,0])
for x in (ax,ax2): x.set_facecolor("#fcfcfb"); [sp.set_visible(False) for sp in x.spines.values()]
Z=M[:,s0:]/1e6; vmax=np.percentile(Z[Z>0],99)
im=ax.imshow(Z,aspect="auto",origin="lower",cmap=cmap,vmin=0,vmax=vmax,
    extent=[matplotlib.dates.date2num(times[s0]),matplotlib.dates.date2num(times[-1]),bins[0],bins[-1]],interpolation="nearest")
ax.plot(times[s0:],cl[s0:],color="#0b0b0b",lw=1.6)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
ax.tick_params(colors="#52514e",labelsize=10); ax.set_ylabel("價格（USDT）",color="#52514e")
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v,_:f"{v/1000:.0f}K"))
ax.grid(axis="y",color="#e4e3df",lw=0.6,alpha=.6)
# right panel: current outstanding
cur=M[:,-1]/1e6; mids=(bins[:-1]+bins[1:])/2
below=mids<P
ax2.barh(mids[below],cur[below],height=step*0.85,color="#2a78d6",label="多單清算（價格下跌觸發）")
ax2.barh(mids[~below],cur[~below],height=step*0.85,color="#eb6834",label="空單清算（價格上漲觸發）")
ax2.axhline(P,color="#0b0b0b",lw=1); ax2.tick_params(left=False,labelleft=False,colors="#52514e",labelsize=9)
ax2.set_xlabel("目前累積（百萬美元）",color="#52514e",fontsize=9)
ax2.legend(loc="upper center",bbox_to_anchor=(0.5,1.07),fontsize=8.5,frameon=False)
# label top clusters
for side,mask in (("多",below),("空",~below)):
    idx=np.where(mask)[0]; top=idx[np.argsort(cur[idx])[-3:]]
    for i in top:
        ax2.text(cur[i],mids[i],f" {mids[i]/1000:.1f}K",va="center",fontsize=8.5,color="#0b0b0b")
cb=fig.colorbar(im,cax=cax,orientation="horizontal"); cb.set_label("每 $250 價格區間的潛在清算量（百萬美元）",color="#52514e",fontsize=9); cb.outline.set_visible(False); cb.ax.tick_params(labelsize=8,colors="#52514e")
ax.set_ylim(bins[0],bins[-1]); ax.set_xlim(times[s0],times[-1])
fig.suptitle(f"BTC 清算熱力圖（估算）｜OKX BTC-USDT 永續｜近 14 天，現價 {P:,.0f}",x=0.06,ha="left",fontsize=15,color="#0b0b0b")
fig.text(0.06,0.015,"模型：依每小時未平倉量增加推估新倉位，多空各半，槓桿分布 3x～100x（以 10x～25x 為主）；價格觸及即視為清算、OI 減少按比例平倉。台灣時間。僅 OKX 單一交易所，非實際倉位資料。",fontsize=8.5,color="#52514e")
plt.savefig(out,dpi=150,bbox_inches="tight",facecolor="#fcfcfb")
# summary
for name,mask in (("LONG",below),("SHORT",~below)):
    idx=np.where(mask)[0]; top=idx[np.argsort(cur[idx])[-5:]][::-1]
    print(name,[(int(mids[i]),round(cur[i],1)) for i in top], "total",round(cur[idx].sum(),1))
print("price",P,"time",times[-1])
# cumulative within ranges
for pct in (0.03,0.05,0.10):
    print(pct, "longs within", round(cur[(mids<P)&(mids>P*(1-pct))].sum(),1), "shorts within", round(cur[(mids>P)&(mids<P*(1+pct))].sum(),1))
