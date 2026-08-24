# Paper Lens Report: Attention Is All You Need

> Hand-reviewed public example for Paper Lens 0.2. It demonstrates the quick-report contract; it is not an independently reproduced result.

<!-- paper-lens:quick:start -->
## Paper information

- Title: Attention Is All You Need
- Authors: Ashish Vaswani and colleagues
- Source: [arXiv 1706.03762v7](https://arxiv.org/abs/1706.03762v7)
- Location convention: PDF pages, 1-based

## Quick read

### One-sentence verdict

The paper replaces recurrence and convolution in sequence transduction with stacked self-attention and feed-forward blocks, yielding a highly parallel architecture whose reported translation quality and training cost made it a strong systems and modeling result (Abstract; Sections 1 and 3; Tables 2–3). This is a summary of the paper's claims, not an independent reproduction.

### Problem and motivation

Dominant sequence-to-sequence models processed tokens recurrently, which constrained within-example parallelism and made long-range dependency paths grow with sequence distance. Section 1 argues that attention already handled many dependencies but was usually coupled to recurrence. The proposed Transformer tests whether attention can carry the full encoder–decoder computation while enabling parallel training.

### Core contributions

- Section 3 specifies an encoder–decoder built from multi-head self-attention, position-wise feed-forward networks, residual connections, and layer normalization.
- Section 3.2 scales dot products by $1/\sqrt{d_k}$ and uses multiple learned projections so heads can attend to different representation subspaces.
- Section 3.5 adds positional encodings because the architecture contains neither recurrence nor convolution.
- Table 1 compares maximum path length, sequential operations, and per-layer complexity against recurrent and convolutional alternatives.

### Method at a glance

Each encoder layer applies multi-head self-attention and a feed-forward sublayer. Each decoder layer adds masked self-attention plus encoder–decoder attention, with masking preventing access to later output positions (Figure 1; Sections 3.1–3.2). The base configuration uses six encoder and six decoder layers, model width 512, eight attention heads, and inner feed-forward width 2048 (Section 3 and Table 3).

For one attention head, Equation (1) computes:

$$ \operatorname{Attention}(Q,K,V)=\operatorname{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V $$

The scaling term controls the magnitude of dot products before the softmax; the paper motivates it as a way to avoid extremely small gradients when $d_k$ is large (Section 3.2.1).

### Claims and evidence

Table 2 reports 28.4 BLEU for the big Transformer on WMT 2014 English-to-German and 41.8 BLEU on English-to-French. The authors present these as improvements over the listed prior systems while using less training computation. Table 3 compares base and big configurations and several ablations, including head count, key/value dimensions, model width, dropout, and positional encoding. These tables support the paper's comparative claims within its reported datasets and setup; they do not establish performance on later tasks or modern benchmarks.

### Limitations and confidence

Confidence is high that the architecture and reported translation results are represented faithfully because they are explicit in Figure 1, Sections 3 and 5, and Tables 1–3. Confidence is lower for broad claims about universal sequence modeling: the main experiments are machine translation, with English constituency parsing as an additional task in Section 6. The report does not verify training code, reproduce BLEU scores, or assess later Transformer variants.

### Recommended follow-ups

For a deep review, inspect how the complexity claims in Table 1 depend on sequence length and representation width; separate evidence for architectural novelty from evidence for optimization choices in Section 5; audit the ablations in Table 3; and compare the original design with later primary literature while keeping external evidence explicitly marked.
<!-- paper-lens:quick:end -->
