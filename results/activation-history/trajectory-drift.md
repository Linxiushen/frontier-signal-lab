# Cross-history trajectory drift (descriptive only)

Dense and norm+attention-preserved INT8 histories start from identical pretrained parameters and advance independently. These comparisons do not share a common anchor. No pass threshold was declared for drift.

| Seed | Step | State | Absolute difference L2 | Relative L2 to dense state | Cosine |
| --- | --- | --- | --- | --- | --- |
| 101 | 4 | parameter | 0.0369379685267 | 5.39229323148e-05 | 0.999999998546 |
| 101 | 4 | exp_avg | 0.353560479341 | 0.036491574122 | 0.999342768287 |
| 101 | 4 | exp_avg_sq | 0.00615687845339 | 0.0349359611854 | 0.999406373118 |
| 101 | 8 | parameter | 0.0479535545929 | 7.00048402062e-05 | 0.99999999755 |
| 101 | 8 | exp_avg | 1.12069834602 | 0.116986295466 | 0.99332575822 |
| 101 | 8 | exp_avg_sq | 0.0142879607453 | 0.0581750839145 | 0.998306454538 |
| 211 | 4 | parameter | 0.0407136964915 | 5.94346839939e-05 | 0.999999998234 |
| 211 | 4 | exp_avg | 1.22770025968 | 0.132137888664 | 0.991385621732 |
| 211 | 4 | exp_avg_sq | 0.0108481490481 | 0.0649322712044 | 0.997891677692 |
| 211 | 8 | parameter | 0.0811474544048 | 0.000118462332098 | 0.999999992984 |
| 211 | 8 | exp_avg | 8.56829931131 | 0.860920536144 | 0.816517302037 |
| 211 | 8 | exp_avg_sq | 0.487025701039 | 1.95490934648 | 0.588776240427 |
| 307 | 4 | parameter | 0.0365200858611 | 5.33126711739e-05 | 0.999999998579 |
| 307 | 4 | exp_avg | 1.4021707108 | 0.129166143319 | 0.991672380826 |
| 307 | 4 | exp_avg_sq | 0.0308888894739 | 0.142270136481 | 0.989943911169 |
| 307 | 8 | parameter | 0.0474736711686 | 6.93039031994e-05 | 0.999999997599 |
| 307 | 8 | exp_avg | 3.42642999844 | 0.30286250816 | 0.953106048834 |
| 307 | 8 | exp_avg_sq | 0.108327913898 | 0.342817000963 | 0.939739165282 |

| Seed | Step | Dense cumulative displacement L2 | Dense update path length | Parameter drift / displacement | Parameter drift / path length |
| --- | --- | --- | --- | --- | --- |
| 101 | 4 | 0.817203141148 | 0.871815581116 | 0.0452004730119 | 0.0423690162539 |
| 101 | 8 | 1.37143257571 | 1.51309334924 | 0.0349660314639 | 0.0316923966503 |
| 211 | 4 | 0.812455862833 | 0.866847612474 | 0.0501118871239 | 0.0469675360531 |
| 211 | 8 | 1.37264302902 | 1.51513277124 | 0.0591176676594 | 0.0535579824719 |
| 307 | 4 | 0.796970003772 | 0.849504623996 | 0.0458236642386 | 0.0429898611844 |
| 307 | 8 | 1.34525080316 | 1.48789930778 | 0.0352898292698 | 0.0319065080011 |

All native counters equal the paired checkpoint. Denominators are nonzero in these six observations. A parameter norm near 685 can obscure changes relative to the actual training displacement; both normalizations are retained.

Seed211 at step8 has first/second-moment relative L2 differences about0.861/1.955 despite passing all common-anchor local update gates. This mixes parameter, gradient, moment and history effects; it is not a moment-only causal result or evidence of quality/convergence/efficiency.

Raw arrays are not published. The standard-library audit verifies reported sufficient-statistic arithmetic, receipt chains and normalized ratios, and sums dense path lengths from receipts. It cannot independently recompute raw native delta norms, cumulative-displacement denominators or state values.

Source stable result SHA256: `c5ae6bbb167189ffe51248258257dc9ed88504e7eed54ce6da2002321c5c80cc`
