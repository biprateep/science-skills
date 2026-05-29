# SCAMPER Framework (Physics & AI Adaptation)

SCAMPER is an acronym for seven ways to approach a problem. It is highly effective for modifying existing mathematical models, physics theories, and algorithmic architectures.

### Substitute
- What elements can be replaced? (Priors, loss functions, boundary conditions, basis functions)
- What other mathematical objects could achieve similar results?
- **AI/Math applications**: 
  - Substitute deterministic PDEs with stochastic differential equations (SDEs).
  - Replace standard softmax attention mechanisms with state-space models (SSMs) or kernelized variants.
  - Substitute L2 regularization with topological or sparsity-inducing priors.

### Combine
- What theories, algorithms, or techniques can be merged?
- **AI/Math applications**:
  - Merge Topological Data Analysis (TDA) with Reinforcement Learning to evaluate state-space coverage.
  - Combine Hamiltonian mechanics with neural networks (e.g., Hamiltonian Neural Networks).
  - Integrate variational inference with normalizing flows.

### Adapt
- What can be borrowed from other fields of physics or math?
- **AI/Math applications**:
  - Adapt renormalization group (RG) techniques to explain or regularize deep learning layers.
  - Use statistical mechanics concepts (like the partition function or free energy) to analyze loss landscapes.
  - Apply differential geometry to optimize along the manifold of a neural network's parameters.

### Modify (Magnify/Minify)
- What can be amplified, reduced, or dimensionally altered?
- **AI/Math applications**:
  - Scale up the dimensions of the Hilbert space in a quantum simulation.
  - Reduce the precision of the statistical estimator (e.g., quantization of weights).
  - Increase the temporal resolution of numerical integrators at the cost of spatial resolution.

### Put to Another Use
- Can this mathematical technique be used in a different context?
- **AI/Math applications**:
  - Repurpose Feynman diagrams for mapping complex Bayesian networks or tensor networks.
  - Use spin-glass theory to model the energy landscape of combinatorial optimization problems.
  - Apply techniques from fluid dynamics to model the flow of information in a network.

### Eliminate
- What assumptions, terms, or variables can be removed?
- **AI/Math applications**:
  - Remove the assumption of Markovian dynamics to explore memory effects.
  - Eliminate the assumption of independent and identically distributed (i.i.d.) data in statistical modeling.
  - Drop higher-order terms in a Taylor expansion to see if a linearized model still holds predictive power.

### Reverse/Rearrange
- Can you invert the process or work backward?
- **AI/Math applications**:
  - Work backward from a desired probability distribution to find the generating Langevin dynamics (diffusion models).
  - Reverse causality: What if the effect is driving the latent cause? (Causal inference adjustments).
  - Invert the sequence of matrix operations to find a more computationally efficient pre-conditioner.
