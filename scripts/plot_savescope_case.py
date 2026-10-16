"""Shareable figure from the reviewed replay, without model execution.

Requires matplotlib==3.10.7 (figure tooling only, not a package dependency).
"""
from pathlib import Path
import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from savescope.report import recorded_case


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = recorded_case()
    rows = [{"batch": run["label"], "gradient_cosine": run["arms"][2]["gradient"]["cosine_similarity"],
             "update_relative_l2": run["arms"][2]["update"]["relative_l2"]} for run in report["runs"]]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
        "axes.spines.right": False, "axes.spines.left": False, "axes.spines.bottom": False,
        "axes.labelcolor": "#4d5b6b", "text.color": "#172331", "xtick.color": "#4d5b6b",
        "ytick.color": "#4d5b6b", "svg.hashsalt": "savescope-v0.1"})
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 5.7), gridspec_kw={"wspace": .4})
    fig.subplots_adjust(top=.70, bottom=.27, left=.07, right=.96)
    fig.set_facecolor("#f6f7f9")
    fig.text(.07,.93,"SaveScope",weight="bold",fontsize=13,color="#245dda")
    fig.text(.07,.85,"Close gradients. Imperfect AdamW steps.",weight="bold",fontsize=23)
    fig.text(.07,.785,"A fixed Pythia-14m diagnostic with exact attention-forward saved tensors",fontsize=11,color="#4d5b6b")
    x = list(range(len(rows)))
    for ax in axes:
        ax.set_facecolor("#f6f7f9")
        ax.set_xticks(x, [r["batch"] for r in rows])
        ax.tick_params(length=0,pad=9)
        ax.grid(axis="y",color="#dfe4eb",linewidth=.8,zorder=0)
        ax.set_xlim(-.6,2.6)
    ax=axes[0]
    ax.scatter(x,[r["gradient_cosine"] for r in rows],color="#245dda",s=80,zorder=3)
    ax.set_ylim(.9985,1.00025)
    ax.set_yticks([.9985,.9990,.9995,1.0000],["0.9985","0.9990","0.9995","1.0000"])
    ax.set_title("Gradient cosine ≈ 0.999",loc="left",fontsize=13,weight="bold",pad=16)
    for i,r in enumerate(rows):
        ax.text(i,r["gradient_cosine"]+.00007,f'{r["gradient_cosine"]:.6f}',ha="center",fontsize=10)
    ax=axes[1]
    ax.bar(x,[r["update_relative_l2"]*100 for r in rows],color="#172331",width=.4,zorder=3)
    ax.set_ylim(0,15)
    ax.set_yticks([0,5,10,15],["0%","5%","10%","15%"])
    ax.axhline(10,color="#93600a",linestyle="--",linewidth=1.4,zorder=4)
    ax.text(.5,.95,"Dashed line: predeclared update-error ceiling",transform=ax.transAxes,ha="center",fontsize=9,color="#93600a")
    ax.set_title("Actual Δθ: three joint gates fail",loc="left",fontsize=13,weight="bold",pad=16)
    for i,r in enumerate(rows):
        ax.text(i,r["update_relative_l2"]*100+.65,f'{r["update_relative_l2"]*100:.2f}%',ha="center",fontsize=11,weight="bold")
    fig.text(.07,.15,"CPU float32 · 3 overlapping synthetic batches · 320 unique target positions",fontsize=10)
    fig.text(.07,.105,"One fresh-state AdamW step, wd=0.01. Not training quality, GPU performance or memory savings.",fontsize=9,color="#4d5b6b")
    fig.text(.07,.055,"Code, protocol and negative results: github.com/Linxiushen/frontier-signal-lab",fontsize=9,color="#245dda")
    output=ROOT/"docs/assets"
    output.mkdir(parents=True,exist_ok=True)
    for suffix in ("svg","png"):
        fig.savefig(output/("first-step-fidelity."+suffix),dpi=180,facecolor=fig.get_facecolor(),metadata={"Date": None} if suffix=="svg" else None)
    svg = output / "first-step-fidelity.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)
    with (output/"first-step-fidelity.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print("Figure source content SHA256: "+report["content_sha256"])


if __name__ == "__main__":
    main()
