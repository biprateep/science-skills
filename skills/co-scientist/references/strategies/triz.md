# TRIZ (Theory of Inventive Problem Solving)

Originally developed for engineering, TRIZ principles apply remarkably well to mathematical and computational challenges by resolving inherent contradictions.

### Key Concepts: Contradictions
Identify competing requirements and find principles that resolve them.

**Example contradictions in Math/Physics/AI:**
- Need high model complexity (accuracy) vs. need low computational cost (efficiency).
- Need high grid resolution (accuracy) vs. limited memory constraints.
- Need robustness to outliers vs. sensitivity to subtle phase transitions.

### Principles for Resolution (Adapted for Computation/Math):
1. **Segmentation**: Distribute computation across multiple independent agents/nodes (federated learning, domain decomposition in PDEs).
2. **Local Quality**: Use mixed-precision arithmetic; allocate high precision only to the most sensitive variables; use adaptive mesh refinement (AMR).
3. **Asymmetry**: Break symmetry to your advantage (e.g., using sparse matrices instead of dense symmetric ones; asymmetrical loss functions).
4. **Prior Action**: Pre-compute values; use caching; perform pre-conditioning on matrices before solving linear systems.
5. **Periodic Action**: Instead of continuous optimization, use learning rate schedulers, or periodically re-orthogonalize vectors in Krylov subspace methods.
6. **Inversion (The Other Way Round)**: Solve the dual problem instead of the primal problem in optimization.
7. **Another Dimension**: Project a non-linearly separable problem into a higher-dimensional space (Kernel trick in SVMs).

### Ideal Final Result
Imagine the perfect solution where the problem solves itself or disappears.

**Questions:**
- What if the neural network automatically pruned itself during training?
- What if the physical system naturally relaxed to the exact mathematical solution without needing an iterative solver?
- What if the data generated its own labels (self-supervised learning)?
