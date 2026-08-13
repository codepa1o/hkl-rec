# Tree Boosting 面试阅读计划

## 目标

这不是论文精读路线。目标是用约 3 小时建立一条能在面试中讲清楚的演进链路：

> Decision Tree -> Random Forest -> Gradient Boosting -> XGBoost -> LightGBM

当前进度（2026-08-06）：已完成决策树前置、Random Forest 和 Friedman
Gradient Boosting；XGBoost 已读到 Section 4.1 `Column Block for Parallel
Learning`，下次从 Section 4.2 的缓存优化继续。

读每篇论文时只回答五个问题：

1. 它要解决什么问题？
2. 输入和输出是什么？
3. 核心算法怎么运行？
4. 相比上一代方法改进了什么，代价是什么？
5. 它如何对应到 `zhihurec` 的 LightGBM 排序链路？

阶段笔记：

- `notes/02-gradient-boosting-machine.md`
- `notes/03-xgboost-vs-lightgbm.md`

## 0. 前置：决策树基础（20 分钟，不读论文）

- [x] 能解释一次树分裂：选择一个特征和阈值，把样本分到左右子树。
- [x] 能解释叶子节点：分类任务输出概率或分数，回归任务输出数值。
- [x] 知道单棵深树容易过拟合、方差大。

验收话术：

> 决策树通过连续的特征阈值判断把样本送到叶子节点。它可解释性强，但单棵树对训练数据变化敏感，因此通常需要多棵树组成集成模型。

## 1. Random Forest：理解 Bagging 对照组（25 分钟）

文件：`01-random-forests-breiman-2001.pdf`

必读：

- [x] Abstract。
- [x] Section 1.1 和 Definition 1.1：Random Forest 的正式定义。
- [x] Section 2.2 `Strength and Correlation`：单棵树要有能力，树之间又不能太相似。
- [x] Section 13 `Remarks and Conclusions`。

跳过：收敛证明、完整实验表、回归部分的详细推导。

面试必须讲明白：

- 每棵树使用不同的 bootstrap 样本和随机特征子集。
- 各棵树互相独立，可以并行训练，最后投票或取平均。
- 目的主要是降低单棵树的方差和过拟合。
- Random Forest 属于 Bagging，不是 LightGBM 的直接祖先，作用是和 Boosting 做对比。

验收问题：

> Random Forest 和 Gradient Boosting 都用了多棵树，为什么前者可以并行，后者通常必须顺序训练？

## 2. Friedman Gradient Boosting：最重要的理论前置（60-75 分钟）

文件：`02-gradient-boosting-machine-friedman-2001.pdf`

必读：

- [x] PDF 第 2-4 页：Section 1、1.1、2，理解“参数空间优化”到“函数空间优化”的转变。
- [x] PDF 第 6-9 页：Gradient Boosting Algorithm 1、Section 4.1 和 4.3。
- [x] PDF 第 16 页：Section 5 `Regularization`，重点理解 learning rate 和树数量。

跳过：L1、Huber、多分类的完整推导，模拟实验和真实数据实验。

面试必须讲明白：

- 整体模型是多棵小树输出结果的加和。
- 第一棵树先给出粗略预测。
- 后一棵树拟合当前损失函数的负梯度；平方误差下可以直观理解为拟合残差。
- 每加入一棵树，模型都沿着降低损失的方向前进一步。
- learning rate 越小，单棵树修正得越谨慎，通常需要更多树。

验收话术：

> Gradient Boosting 不是让多棵树独立投票，而是顺序训练。每一轮根据当前模型的错误计算负梯度，再训练一棵小树去拟合这个修正方向，最后把所有树的结果加起来。

## 3. XGBoost：理解正则化和工程化 GBDT（45-60 分钟）

文件：`03-xgboost-chen-guestrin-2016.pdf`

必读：

- [x] Section 1 `Introduction`。
- [x] Section 2.1-2.3：正则化目标、Gradient Tree Boosting、Shrinkage 和列采样。
- [x] Section 3.1：树节点的分裂收益如何计算。
- [x] Section 3.4：缺失值和稀疏特征如何处理。
- [ ] Section 4：已读 4.1，继续读后续小节开头，理解系统优化方向。
- [x] Section 7 `Conclusion`。

跳过：Section 3.3 Weighted Quantile Sketch 的证明和 Section 6 的完整实验。

面试必须讲明白：

- XGBoost 仍然属于 Gradient Boosting。
- 训练目标不仅考虑预测损失，还显式惩罚树的复杂度。
- 使用一阶、二阶梯度近似目标函数，并用 split gain 选择分裂。
- Shrinkage、列采样和复杂度正则化共同控制过拟合。
- 稀疏感知、缓存优化和并行分裂让它更适合生产数据。

验收问题：

> XGBoost 相比原始 Gradient Boosting，算法目标和工程实现分别增加了什么？

## 4. LightGBM：理解为什么训练更快（40-50 分钟）

文件：`04-lightgbm-ke-et-al-2017.pdf`

必读：

- [ ] Abstract 和 Section 1 `Introduction`。
- [ ] Section 2.1：GBDT 的训练复杂度瓶颈。
- [ ] Section 3.1：GOSS 算法流程。
- [ ] Section 4：EFB 算法流程。
- [ ] Section 5.2、5.3：分别确认 GOSS 和 EFB 的实验作用。
- [ ] Section 6 `Conclusion`。

跳过：Section 3.2 的理论证明和大部分实验表格。

面试必须讲明白：

- GOSS 解决样本数量太大的问题：保留梯度大的难样本，只抽样一部分梯度小的简单样本，并对抽样结果做权重补偿。
- EFB 解决稀疏特征太多的问题：把几乎不会同时非零的特征打包到同一列。
- 两者分别减少有效样本数和有效特征数，在尽量保持精度的同时减少训练时间和内存占用。
- LightGBM 不是新的模型家族，仍然是 GBDT 的高效实现。

验收问题：

> 为什么不能直接把所有梯度小的样本删掉？EFB 又为什么不会让被打包的两个特征相互混淆？

## 5. 映射回 zhihurec（20 分钟）

- [ ] 找到 `backend/app/repositories/ranker.py` 的 `RANKER_FEATURE_COLUMNS`。
- [ ] 找到 `score_candidates()` 如何把具名特征按固定顺序转换成数值矩阵。
- [ ] 找到 `build/mind_models/lgb_ranker_v1.txt` 和配套 metadata。
- [ ] 能说明当前模型使用 16 个结构化特征预测候选文章点击概率，再按预测分排序。
- [ ] 能说明项目调用了 LightGBM 库，没有自己实现 GOSS、EFB 或树训练算法。

最终 60 秒回答：

> 单棵决策树容易过拟合。Random Forest 用多棵独立树投票降低方差；Gradient Boosting 改成顺序训练，让后一棵树拟合前面模型的负梯度，不断降低损失；XGBoost 在此基础上加入模型复杂度正则化、二阶梯度和稀疏感知等工程优化；LightGBM 再通过 GOSS 减少有效训练样本，通过 EFB 减少有效特征数量，从而降低训练时间和内存开销。我们的项目把 16 个推荐特征输入 LightGBM，预测候选文章的点击概率，然后按预测分排序。

## 论文与来源

1. `01-random-forests-breiman-2001.pdf`
   - Leo Breiman, "Random Forests", 2001.
   - 来源：https://www.stat.berkeley.edu/~breiman/randomforest2001.pdf

2. `02-gradient-boosting-machine-friedman-2001.pdf`
   - Jerome H. Friedman, "Greedy Function Approximation: A Gradient Boosting Machine", 2001.
   - 下载来源：UIUC 公开课程镜像。
   - 规范出版地址：https://doi.org/10.1214/aos/1013203451

3. `03-xgboost-chen-guestrin-2016.pdf`
   - Tianqi Chen and Carlos Guestrin, "XGBoost: A Scalable Tree Boosting System", 2016.
   - 来源：https://arxiv.org/abs/1603.02754

4. `04-lightgbm-ke-et-al-2017.pdf`
   - Guolin Ke et al., "LightGBM: A Highly Efficient Gradient Boosting Decision Tree", 2017.
   - 来源：https://proceedings.neurips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html

`Classification and Regression Trees` (CART, 1984) 是书籍而不是论文，因此没有复制到当前目录。
