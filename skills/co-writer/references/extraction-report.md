# Extraction report — five papers, read 2026-09-10

Run of [extraction.md](extraction.md) over the prose of five papers. This is
evidence, not rules. [voice-profile.md](voice-profile.md) decides what becomes
a rule; this file is where every rule's supporting instances live.

Doc ids: **DESI** (AAS journal, 2024, ~11.5k words), **ENC** (MNRAS, 2021,
~11k), **RECAL** (NeurIPS workshop, 2021, ~1.8k), **PENG** (NeurIPS workshop,
2026, ~1.7k), **PRAT** (NeurIPS workshop, 2026, ~1.5k).

One thing the read turned up that shapes everything below: **the two 2026
papers diverge from the 2021–2024 three** on a specific, listable set of
constructions — sentence-initial evaluative adverbs, priority claims,
intensified nouns. Findings note it where it occurs; the interview asks
which register is the target.

---

## A. Section moves

### A.1 Abstract runs two or three sentences of scientific need before the first "We"
Tier: ALL · Genre: UNSURE
Pattern: No abstract opens with "We present". The first-person contribution sentence is the second (PRAT), third (DESI, ENC, PENG) or fifth (RECAL) sentence; what precedes it is the physical quantity and why it matters.
Evidence:
- [DESI, Abstract] "Deep spectroscopic samples can improve photometric redshift (photo-$z$) estimates and reduce uncertainties on redshift distributions. Such improvements can increase the cosmological constraining power … We present results from the “DESI-Deep pilot” program"
- [ENC, Abstract] "Studies of cosmology, galaxy evolution, and astronomical transients … are all critically dependent on estimates of photometric redshifts. Capsule networks are a new type of neural network architecture … We use a deep capsule network"
- [RECAL, Abstract] "Many astrophysical analyses depend on estimates of redshifts (a proxy for distance) determined from photometric (i.e., imaging) data alone. Inaccurate estimates … can result in large systematic errors. However, … We leverage a recently developed regression technique"
- [PRAT, Abstract] "Stellar streams are thin, elongated collections of stars formed by gravitational disruption … We present SCREAM"
Counter-evidence: none. Common in the genre, but "We present…" openers are common too and never occur here.

### A.2 Introduction opens at the definitional level, even in a four-page paper
Tier: ALL · Genre: GENRE (funnel intro) — but the funnel starts unusually wide
Pattern: The first sentence of every introduction states what the central physical quantity is or does, before any survey, method, or gap.
Evidence:
- [DESI, Introduction] "Photometric redshifts (photo-$z$'s) -- i.e., estimates of galaxy redshifts obtained from photometric data alone -- are essential to the success of ongoing and upcoming imaging-based astrophysical experiments."
- [ENC, Introduction] "Wide-field extra-galactic sky surveys collect photometric or spectroscopic measurements to create 3-dimensional maps of the Universe by measuring on-sky positions and redshifts of a variety of astronomical objects."
- [RECAL, Introduction] "Galaxy distance, as measured by redshift, is essential for estimating intrinsic luminosity and 3D location in space, which is crucial information for many astrophysical studies."
- [PENG, Introduction] "Understanding galaxy evolution requires characterizing galaxy properties such as chemical composition, star formation rates, and stellar ages"
- [PRAT, Introduction] "Stellar streams are narrow, extended structures formed when gravitationally bound progenitors (e.g., globular clusters, dwarf galaxies) are disrupted by their host's gravitational field [cite]."

### A.3 Gap paragraph opens "However," and the next paragraph opens with the contribution
Tier: ALL · Genre: GENRE
Pattern: The limitation of prior work is a paragraph beginning "However," (or a "though none can…" clause); the contribution paragraph that follows opens "In this work, we…" / "This work addresses…" / "We present…". The gap is often a list of three or four shortcomings.
Evidence:
- [DESI, Introduction] "However, DESI's redshift measurement performance for fainter objects, particularly at LSST-like depths, is largely untested. This work addresses this need by studying DESI's performance for galaxies at depths comparable to…"
- [RECAL, Introduction] "Several previous works have studied PDF re-calibration (e.g., [Author et al.]), though none can ensure that PDFs are well-calibrated at every point in feature space. … In this work, we develop a local PDF re-calibration procedure"
- [PRAT, Introduction] "However, these methods often ignore uncertainties in the input measurements, employ heavy post-processing (e.g., line-finding algorithms), and focus primarily on identifying new stream candidates … We present SCREAM"
- [ENC, Introduction] "Deep neural network-based methods are continuing to improve but have substantial limitations in terms of the interpretability of the features learnt from images and efficiency in training. … To alleviate some of these issues, we explore the use of a modern deep learning method called capsule networks"

### A.4 Roadmap paragraph closes the introduction of journal papers only
Tier: JOURNAL · Genre: GENRE
Evidence:
- [DESI, Introduction] "This article is organized as follows. In Section [ref], we describe our target selection, observations, and data processing. In Section [ref], we detail our methods…"
- [ENC, Introduction] "The paper is organised as follows. In Sec. [ref], we discuss the various data sets used in this work. In Sec. [ref] we introduce the concept of capsule networks…"
Counter-evidence: absent from all three workshop papers.

### A.5 Every named technique gets a plain-language explanation at first use, including standard ones
Tier: ALL (heaviest in JOURNAL) · Genre: DISTINCTIVE
Pattern: Logistic regression, CNNs, UMAP, SHAP, distance correlation, I-splines, CATHODE, Redrock — each is explained in one to four sentences of tutorial prose before being used, whether or not the venue's readers would know it. The explanation states what the thing is, then what it does, then why it is used here.
Evidence:
- [ENC, Introduction] "Artificial neural networks are mathematical models, originally developed to mimic the logical operations of the human brain. The simplest unit of such a model (also called an artificial neuron) is a linear transformation of an input followed by some non-linear function (also called an activation function)."
- [DESI, Methods] "We therefore use a generalized linear model with a Binomial likelihood (also known as logistic regression; see [Author et al.] for a discussion on the topic) to model the observed success rate"
- [ENC, Results] "The distance correlation quantifies the dependence between two random variables by measuring how much the Euclidean distance between two samples of one random variable changes for a given change in distance between two samples of another random variable. This makes the distance correlation sensitive to any kind of dependence"
- [ENC, Results] "SHAP is a method to explain a prediction by computing the contribution of each feature. It takes a game theory approach to optimally distribute credit to each feature"
- [RECAL, Re-calibration] "$I$-splines are monotonic functions, a linear combination of which with non-negative coefficients gives us any arbitrary monotonic non-decreasing function."
- [PRAT, Methods] "We build our algorithm by extending CATHODE [cite], a weakly-supervised anomaly detection method originally developed to identify anomalous populations in high-dimensional particle physics data."
- [DESI, Data] "Redrock is the software employed in the DESI data processing pipeline to determine redshifts from observed spectra. It evaluates each spectrum against a set of template spectra by first carrying out a broad redshift search, and then performing a more detailed fit"

### A.6 Results are narrated from the figure: figure as subject, then "We see that" / "We observe that"
Tier: ALL for figure-as-subject; JOURNAL + RECAL for "We see that" · Genre: DISTINCTIVE
Pattern: A results paragraph opens "Figure [ref] shows …", and the interpretation follows as "We see that …" or "We observe that …". The 2026 papers keep the figure-as-subject opener but switch to "demonstrates" / "we find".
Evidence:
- [DESI, Results] "Figure [ref] shows the redshift measurement success rate as a function of exposure time in bins of $i$-band magnitude. As expected, we observe that the success rate increases with increasing exposure times at a given magnitude. We see that for the brighter objects…"
- [ENC, Results] "We show a comparison between the photometric and the spectroscopic redshifts for the test set in Fig. [ref]. We see that the scatter is tight and distributed symmetrically about the $z_{\mathrm{phot}}=z_{\mathrm{spec}}$ line."
- [ENC, Results] "Fig. [ref] shows the 2-dimensional UMAP embedding of the 16-dimensional capsules colour coded by various properties. When coloured by photometric or spectroscopic redshift (top row), the embedding shows a nearly perfect redshift sequence."
- [RECAL, Results] "Fig. [ref] shows the local P-P plots for a random subset of galaxies from TEDDY-C. … We see that the P-P plots follow the identity line more closely after global re-calibration"
- [PENG, Results] "Figure [ref] (right) demonstrates that the model accurately reconstructs DESI spectra at precise fiber locations"
- [PRAT, Results] "Figure [ref] visualizes the algorithm performance with respect to STREAMFINDER. Spatially (top-left), SCREAM uniquely recovers the stream's diffuse “cocoon”"
Counts of "We see that": ENC 8, RECAL 2, DESI 1, PENG 0, PRAT 0. "We observe that": DESI 5, ENC 3.

### A.7 Concessive sentence: "While / Though / Although X, Y" — used to bind a limitation to a result in one sentence
Tier: ALL · Genre: DISTINCTIVE
Pattern: A caveat and its answer share a sentence, caveat first. This is the dominant way scope is limited and negative results are attached to positive ones. Sentence-initial "Though" (rare in American academic prose) occurs in three papers.
Evidence:
- [DESI, Discussion] "While a detailed, component-by-component comparison of the two facilities is complex and beyond the scope of this work, we discuss a few key factors in instrumentation, data processing and observing strategy that likely contribute to these differences"
- [ENC, Capsule Networks] "Though CNNs are invariant to translations by design [cite], they use pooling layers (i.e. replacing the input with the local maximum or average value) to locally combine the signal"
- [RECAL, Abstract] "Though we focus on an example from astrophysics, our method can produce PDFs which are calibrated at all locations in feature space for any use case."
- [RECAL, Results] "Though the method works reasonably well when the distribution of features for the calibration set is slightly different from the test set, we expect performance to worsen if the distribution of features for the test set is drastically different."
- [PENG, Results] "Although the spectral predictions are slightly over-confident and image predictions moderately under-confident, the uncertainties remain well-calibrated overall."
- [PRAT, Introduction] "While approaches like STREAMFINDER [cite] are highly successful, they depend on assumed models of the Milky Way's gravitational potential and rigid stellar evolution priors."
- [PRAT, Methods] "Although these class probabilities are miscalibrated, they preserve a monotonic relationship with the true underlying signal probabilities [cite]."
- [DESI, Methods] "The DESI spectroscopic data reduction and redshift measurement pipelines, while extremely efficient, have only been optimized for the classes of objects observed during the main survey."

### A.8 Closing paragraph reaches to future work with the fixed phrase "in a future work"
Tier: ALL (PENG uses "future work should explore") · Genre: DISTINCTIVE (the article "a")
Evidence:
- [ENC, Results] "A systematic study of these outlier galaxies will be done in a future work."
- [ENC, Results] "we expect that capsule-based encodings can be used to create a general purpose image-based inference methodology … and will be explored in a future work."
- [RECAL, Results] "A systematic study to understand the performance of this method for various distributions of input features will be performed in a future work."
- [PRAT, Results] "A thorough vetting of our algorithm on mock data will also be performed in a future work."
- [DESI, Results] "We are also working to develop automated methods for identifying reliable redshifts based on alternative metrics, which will be discussed in a future work."
- [ENC, Introduction] "In a future paper, we plan to extend our methods and produce locally calibrated PDFs"

### A.9 Journal summary sections recap each result with a parenthetical pointer
Tier: JOURNAL · Genre: GENRE
Evidence:
- [ENC, Summary] "We achieve a photometric redshift prediction accuracy comparable to or better than current methods while requiring less data and fewer trainable parameters (see Figs. [ref] & [ref]). The performance of our algorithm is stable across the brightness and redshift range of our data set (see Fig. [ref])."
- [DESI, Summary] "We find that DESI is remarkably efficient at this task; with just two hours of exposure time, it can match or exceed the redshift success rates of the DEEP2 and DEEP3 surveys"

### A.10 Final sentence of the paper is forward-looking and concrete, never a slogan
Tier: ALL · Genre: GENRE
Evidence:
- [ENC, Summary] "With growing high-$z$ spectroscopic training sets and rapidly progressing capsule network architecture development, we are optimistic that capsule networks will provide complementary constraints or even superior photo-$z$'s to template-based methods at high-$z$."
- [DESI, Summary] "…would be transformative for cosmology, dramatically improving the precision of cosmological constraints from LSST and providing a lasting legacy resource for all of extragalactic astronomy."
- [PRAT, Results] "Finally, implementing a scanning signal-region window and sampling from full, non-diagonal error covariance matrices will enable blind, all-sky searches and improved classification across multiple Milky Way streams."
Counter-evidence: [PENG, Results] "Furthermore, our method holds substantial potential for broader multi-modal applications in fields such as remote sensing and biology." — the one closer that is a reach rather than a plan.

---

## B. Paragraph architecture

### B.1 Paragraphs end on a consequence sentence: "Therefore," / "Consequently," / "Thus," / "Hence" / "This …"
Tier: ALL · Genre: DISTINCTIVE
Pattern: The last sentence of a paragraph draws the conclusion of the preceding facts, opened by a consequence connective. "Therefore" is the workhorse (DESI ≈10, ENC ≈5, RECAL 2, PENG 1, PRAT 1); "Hence" is ENC's (4).
Evidence:
- [DESI, Introduction] "Therefore, magnitude-limited spectroscopic samples that match the depths of the photometric samples used in a study and include minimal selection cuts can offer a way forward to mitigate these biases."
- [DESI, Data] "Consequently, the results presented in this work using HSC-based magnitudes should be considered conservative."
- [PRAT, Methods] "Since the generated data models the background, the classifier cannot differentiate the two without a signal. Thus, any learned separation is directly attributable to the stellar stream signal."
- [ENC, Introduction] "A sufficiently deep or wide fully connected network can be used to approximate any function [cite] and hence can be used to effectively predict photometric redshifts."
- [ENC, Data] "This step is done to remove the small number ($<1\%$) of problematic measurements of galaxy properties that can affect our analysis."

### B.2 Sentence-initial bare "This" as the glue between sentences
Tier: ALL · Genre: DISTINCTIVE
Pattern: Consecutive sentences are linked by a demonstrative subject with no noun — "This yields…", "This shows that…", "This is because…", "This allows us to…". Dozens per journal paper. Editors often flag "vague this"; here it is the primary cohesion device.
Evidence:
- [DESI, Data] "This has enabled the tests of DESI's performance for broadly-selected samples of faint galaxies described in this paper."
- [DESI, Methods] "This yields a reliable quantification of the SNR of the spectral continuum, while being resilient to any anomalies"
- [ENC, Results] "This shows that having images with a higher signal-to-noise ratio improves the quality of photo-$z$ predictions."
- [ENC, Training] "This is because the logistic transformation makes the distribution of the target variable … fall gradually at the boundaries"
- [RECAL, Re-calibration] "This means that our corrected PDF equals the initial PDF multiplied by a correction factor"
- [PENG, Methods] "This also disproportionately exposes the model to cases where an entire modality is missing"
- [PRAT, Introduction] "This preserves anomaly score statistics and enables the discovery of members that rigid models might miss."
Also the "This [noun]" form: "This enhanced throughput results from…", "This large difference in astrometric accuracy could…", "This near-IFU capability reflects…".

### B.3 Paragraphs are long and single-topic; no one-sentence paragraphs
Tier: ALL · Genre: UNSURE
Pattern: Journal paragraphs average 105–125 words and run to 300+ (ENC's CNN-history paragraph). The only sub-two-sentence paragraphs are equation sandwiches (a "where" clause). There is no one-sentence paragraph used for emphasis anywhere in 33k words.
Evidence: [ENC, Introduction] the paragraph beginning "If the input data are images, then the number of trainable weights…" runs ~330 words through the whole CNN-for-photo-z literature. [DESI, Data] the observing-conditions paragraph "We observed a total of 4863 targets…" carries eleven numbers in ~200 words.

### B.4 Steps are narrated "We first … We then … Next, … Finally, …"
Tier: ALL (PENG 0) · Genre: DISTINCTIVE
Evidence:
- [DESI, Data] "We first queried for all unique sources … We then correct all apparent magnitudes … We then selected galaxies that have…"
- [DESI, Methods] "We first subtract the best-fit Redrock template spectrum … We then divide the wavelength range into 64 bins … The final empirical SNR is then calculated as the median"
- [ENC, Training] "We then use this network to predict morphology labels … We then calibrate the predicted class probabilities … We then select galaxies with calibrated class probabilities over 0.8 … We train the same network again"
- [PRAT, Methods] "We first partition the data into two non-random subsets … Next, we perform conditional density estimation … A neural network then classifies…"
Counter-evidence: never "Firstly / Secondly"; never a numbered list for procedure.

---

## C. Sentence rhythm

### C.1 Purpose-infinitive opener: "To [verb] …, we …"
Tier: ALL · Genre: DISTINCTIVE
Pattern: The most common way a methods sentence begins is with its purpose. Twenty-plus instances across the corpus.
Evidence:
- [DESI, Methods] "To isolate the impact of target selection from instrument performance, we entirely excluded objects that had reliable redshift estimates but were spectroscopically classified as stars"
- [DESI, Methods] "To decouple these two effects, we therefore calculate an adjusted redshift measurement success rate"
- [DESI, Methods] "To ensure the robustness of our findings, we performed an empirical measurement of the SNR which is independent of the DESI spectroscopic pipeline."
- [ENC, Results] "To check whether the components of the capsules represent any visually identifiable properties of the galaxies, we take the capsule corresponding to the predicted morphology"
- [ENC, Results] "To quantify this, we calculate the SHapley Additive exPlanations (SHAP; [Author et al.]) values"
- [PENG, Methods] "To encourage robust cross-modal representation learning, we independently mask the image and spectral sequences."
- [PENG, Methods] "To discourage the model from over-inflating $\boldsymbol{\sigma}_{\text{pred}}^2$ on masked patches … we apply a complementary $L_2$ regularization penalty"
- [PRAT, Methods] "To prevent class imbalance, we generate the same number of samples as the true SR observations."
- [PRAT, Methods] "To increase stochastic regularization, we set $M=10$ during training."

### C.2 The parenthetical gloss "(also called X)" / "(also known as X)" / "(i.e., …)" / "(e.g., …, etc.)"
Tier: ALL · Genre: DISTINCTIVE for "(also called …)" and for "e.g., … etc."; GENRE for i.e./e.g. density
Pattern: Terms are glossed inline in parentheses, not in footnotes or separate sentences. "i.e.," and "e.g.," always take the comma. An "e.g." list frequently closes with "etc." (ENC 6, DESI 3) — redundant by style guides, consistent here.
Evidence:
- [ENC, Introduction] "(also called an artificial neuron)", "(also called an activation function)", "(also called weights)"
- [ENC, Capsule Networks] "transposed convolutional layers (also called de-convolution layers)"
- [ENC, Loss Functions] "the Margin Loss (also called the Hinge loss)"
- [DESI, Methods] "(also known as logistic regression; see [Author et al.] for a discussion on the topic)", "the inverse of the logit function (also called the sigmoid function)"
- [RECAL, Re-calibration] "(also called Amortized Local P-P plots or ALP plots)"
- [PRAT, Introduction] "finding member stars of an already known stream (also called characterization)"
- [ENC, Introduction] "measure their intrinsic properties (like luminosity, mass, star formation rate, etc.)"
- [ENC, Capsule Networks] "a set of “instantiation parameters” for the entity (e.g., location, size, orientation, colour, etc.)"
- [DESI, Methods] "resilient to any anomalies, strong spectral features, etc."

### C.3 Short sentences carry setup facts, never emphasis
Tier: ALL · Genre: DISTINCTIVE
Pattern: Sentences under twelve words (6–8% of all) are flat statements of a data or configuration fact. None is a rhetorical beat, none stands alone as a paragraph.
Evidence:
- [ENC, Data] "No foreground/background objects were removed."
- [ENC, Appendix] "The number of iterations is a tunable hyper-parameter."
- [DESI, Discussion] "A typical DEEP2/3 exposure time was approximately 1 hour."
- [PENG, Methods] "Masking is applied independently to each modality."
- [PENG, Methods] "We mask missing channels and non-finite measurements."
- [PRAT, Methods] "Every observation falls into either the SR or SB based strictly on its $\mu_{\phi_1}$ value."

### C.4 Sentence-initial connectives are frequent and drawn from a fixed set
Tier: ALL · Genre: UNSURE (each is ordinary; the density and the set are his)
Pattern: "Therefore,", "However,", "Moreover,", "Furthermore,", "Similarly,", "Specifically,", "In contrast,", "Consequently,", "As a result,", "As expected,", "Following [Author et al.],", "Since …,", "Given …,". "In contrast" ×5 in DESI alone. "Moreover" ENC 6.
Evidence:
- [DESI, Discussion] "In contrast, DESI employs the “spectro-perfectionism” algorithm of [Author et al.]." / "In contrast the HSC-SSP PDR3 catalog we use for targeting has been able to…" / "In contrast, our pilot survey implemented an observing strategy…"
- [ENC, Introduction] "Moreover, the fact that farther objects appear to be smaller and fainter to an observer also give us an additional piece of information"
- [DESI, Methods] "Specifically, the processed spectra, along with an initial redshift measurement from Redrock, were used to create interactive web pages"
- [PENG, Methods] "Following vision transformers [cite], images are divided into $16 \times 16$ pixel patches"
Counter-evidence: "Firstly", "Overall,", "In summary," never occur; "In conclusion," occurs once (PENG, 2026).

### C.5 Long sentences are held together by relative clauses and a closing "which" clause; mean 25–28 words in journal papers, 20–27 in workshop papers
Tier: ALL · Genre: GENRE
Evidence:
- [DESI, Introduction] "[Author et al.] laid out a proposal for such a sample arguing approximately 20,000 spectra, distributed over multiple wide sky fields and matching the depths of imaging surveys, should be sufficient to meet the photo-$z$ and calibration requirements for next-generation astrophysical experiments like LSST; both past theoretical forecasts and the scaling of errors with training set size for machine learning algorithms lead to numbers of this order." (58 words)
- [ENC, Introduction] "Most traditional methods for quantifying galaxy morphology, like ellipticity and S ersic index, cannot fully encode all of the visual information that an image of a galaxy provides and hence methods that use images of galaxies directly as inputs (e.g. [Author et al.]) and rely on artificial neural networks are the current state-of-the-art." (52 words)

### C.6 Restrictive "which" without a comma
Tier: ALL · Genre: DISTINCTIVE (a grammar habit, not a genre convention)
Evidence:
- [DESI, Data] "Some additional observations were carried out in a region between … which we label the DESI-Hercules field."
- [ENC, Introduction] "finding a set of parameters (also called weights) for these transformations which will minimise a loss function"
- [ENC, Results] "dimension 2 which we saw control the visual size of the galaxy image has the strongest correlation"
- [RECAL, Introduction] "tests like the ones proposed in [Author et al.] and [Author et al.], which we will leverage in our method"
- [PRAT, Methods] "the value of a single feature. We define SR using the along-stream proper motion, $\mu_{\phi_1}$, as streams are tightly kinematically constrained"

---

## D. Claim strength and hedging

### D.1 Result verbs: find / observe / see in 2021–2024; demonstrate / prove / highlight in 2026
Tier: JOURNAL+RECAL vs CONFERENCE-2026 · Genre: DISTINCTIVE (the split)
Pattern: The earlier papers state results with "We find that", "We observe that", "We see that", "This shows that", "This indicates". The 2026 papers reach for "demonstrates", "This proves that", "highlight", "for the first time".
Evidence, 2021–2024:
- [DESI, Results] "we find that roughly 5 to 10% of the redshift measurement failures are due to $z>1.6$ objects"
- [ENC, Results] "We find a significantly smaller spread in the predictions ($\sigma_{\mathrm{NMAD}}=0.00741$)"
- [ENC, Results] "This shows that some of the features learnt by the capsule network correspond to physical properties of galaxies."
- [RECAL, Results] "We find that the local re-calibration method tends to outperform the global re-calibration in most cases."
Evidence, 2026:
- [PENG, Results] "This proves that unsupervised cross-modal pretraining effectively captures the necessary spatio-spectral structures"
- [PENG, Results] "we demonstrate for the first time the prediction of high-resolution, spatially resolved spectra"
- [PRAT, Abstract] "Our results highlight the transformative potential of uncertainty-aware, weakly-supervised ML"
- [PRAT, Abstract] "Crucially, SCREAM is the first machine learning (ML) framework in this domain to directly incorporate observational uncertainties"

### D.2 Causal interpretation is hedged with a fixed vocabulary
Tier: ALL (heaviest JOURNAL) · Genre: DISTINCTIVE (the specific phrases)
Pattern: "This might be because", "This can be attributed to", "We suspect this is because", "Most likely, … arise because", "We hypothesise that", "likely contribute", "may partly explain". A mechanism is always offered, and always hedged.
Evidence:
- [ENC, Results] "This might be because elliptical galaxy populations have similar rest-frame colours as older stellar populations tend to change very little in colour with time."
- [ENC, Results] "This can be attributed to the fact that there is less training data and increased noise in the images at these regimes."
- [ENC, Results] "We suspect this is because, at very low redshifts resolved information in the images like morphology, size, and surface brightness. contains rich information about galaxy distances."
- [ENC, Results] "Most likely, these correlations arise because SFR and sSFR depend on galaxy magnitudes and spectroscopic redshifts which the capsules efficiently encode, but the capsules may also encode some physical properties"
- [ENC, Results] "We hypothesise that dimension 8 learns a representation which is a combination of the morphological type, colour, and orientation"
- [DESI, Discussion] "These differing strategies for determining exposure times may partly explain the observed differences in redshift measurement efficiency. However, even under the most favorable assumptions, a factor of 1.5 in effective exposure time is insufficient to fully explain the total difference"
- [DESI, Discussion] "It is uncertain which if any of these factors is the dominant explanation … However, all of them work in the same direction."
- [PENG, Results] "While this self-similarity assumption is well-grounded for the bulk galaxy population, performance may degrade for morphologically peculiar systems"

### D.3 Negative results sit in the same paragraph as the positive one, introduced by "However," and given a mechanism
Tier: ALL · Genre: DISTINCTIVE (integration rather than a Limitations section)
Evidence:
- [PRAT, Results] "Photometrically (right), minimizing physical priors allows SCREAM to recover fainter member stars that SF misses. However, the model struggles with brighter Red Giant Branch (RGB) stars as their lower feature-space density causes the anomaly detector to miss them."
- [ENC, Results] "Some of the dimension 10 outliers in the main redshift sequence clearly have stars in the image. However, our investigation of the dimension 10 outliers in the smaller sequence has yet to yield a clear interpretation."
- [DESI, Discussion] "The relative impact of resolution versus wavelength range is not entirely clear, however; both DEEP2 and DEEP3 delivered similar overall redshift measurement success rates to each other, despite differing by roughly a factor of two"
- [PENG, Results] "adhere closely to independent MaNGA Data Release 17 ground-truth observations, with slight under-prediction of H$\alpha$ fluxes in select star-forming regions."
- [DESI, Methods] "Therefore, these adjusted success rates should be considered to be estimates based on currently available data which may have inaccuracies when extrapolated."

### D.4 Surprise and expectation are marked explicitly, with one adverb
Tier: ALL · Genre: DISTINCTIVE (the specific set: remarkably / unsurprisingly / as expected; not interestingly / notably)
Evidence:
- [DESI, Abstract] "We find that DESI is remarkably efficient at this task"
- [DESI, Results] "Remarkably, we also see that with about 2 hours of exposure time, DESI can match the redshift measurement success rate of the DEEP2 and DEEP3 surveys."
- [DESI, Results] "As expected, we observe that the success rate increases with increasing exposure times"
- [ENC, Results] "Unsurprisingly, we find that many of the capsule components have strong correlations with the spectroscopic redshift"
- [DESI, Discussion] "It is therefore not surprising that DESI should be more efficient than prior surveys, but it was not expected that the difference in redshift measurement efficiency would be so high."
Counter-evidence: sentence-initial "Interestingly" occurs nowhere. "Importantly," once (RECAL). "Notably," once, in a 2026 caption. "Crucially," once, 2026 abstract.

### D.5 Priority claims and "novel" appear only in 2026
Tier: CONFERENCE-2026 · Genre: DISTINCTIVE (by absence elsewhere)
Evidence:
- [PENG, Introduction] "we present a novel uncertainty-aware, multi-modal foundation model"
- [PENG, Introduction] "our architecture enforces cross-modal fusion through masked reconstructions and uniquely incorporates both fiber location and cosmological redshift"
- [PRAT, Results] "To our knowledge, SCREAM is among the first ML-based stellar stream identification and characterization frameworks to incorporate observational uncertainties"
- [PRAT, Methods] "Though novel for this domain, a similar approach to incorporate input measurement uncertainties have been used in other contexts"
Counter-evidence: "novel" does not occur in DESI, ENC, or RECAL. The 2021 papers describe their contribution as "we explore the use of", "we develop a … procedure".

### D.6 "significantly" is used freely, both statistically and as an intensifier
Tier: ALL · Genre: UNSURE
Pattern: DESI ≈15, ENC ≈8, PENG 2, PRAT 1. "significantly larger", "significantly enhance", "significantly lower", "significantly more efficient", "significantly limits". Never accompanied by a p-value.
Evidence:
- [DESI, Data] "The field of view of DESI ($\sim$8 sq. degs.) is significantly larger than the portions of these fields with the most extensive imaging."
- [ENC, Data] "the Stripe 82 galaxies which satisfy our magnitude and redshift cuts defining the parent sample have significantly less noise than the other images."
- [PENG, Introduction] "which significantly limits their scientific utility"

---

## E. Positioning against prior work

### E.1 Prior work is a grammatical agent with a specific verb, then a "They …" sentence describing what it did
Tier: ALL (heaviest JOURNAL) · Genre: DISTINCTIVE (the mini-narrative per cited method)
Evidence:
- [ENC, Introduction] "[Author et al.] modified the ImageNet challenge-winning AlexNet [cite] to $griz$ images of $\sim$64,000 SDSS galaxies, finding comparable accuracy to the best tree-based classical machine learning algorithms. [Author et al.] combined a CNN and a mixture density network to produce photo-$z$ Probability Density Functions"
- [ENC, Introduction] "[Author et al.] produced the current best photo-$z$’s using a supervised algorithm for the SDSS Main Galaxy Sample … They applied an innovative deep CNN that included five inception modules [cite] … They pre-trained their network on a very large unlabelled data set"
- [DESI, Introduction] "[Author et al.] laid out a proposal for such a sample … They also provided estimates of the time required to obtain such samples"
- [RECAL, Introduction] "[Author et al.] described a method to re-calibrate PDFs using a single correction factor based on the overall distribution of PIT values, which ensures a uniform global distribution of PIT values, but this single correction factor is applied to all PDFs and does not account for local variations."
- [ENC, Capsule Networks] "Though [Author et al.] introduced the idea of a capsule network, a concrete architecture and training methodology was not proposed. More recently, [Author et al.] proposed a training method called the dynamic routing algorithm which made capsule networks viable."

### E.2 Competing work is credited before it is criticized
Tier: ALL · Genre: DISTINCTIVE
Pattern: The critique of a method is always preceded, in the same sentence or the one before, by an acknowledgement of what it does well.
Evidence:
- [PRAT, Introduction] "While approaches like STREAMFINDER [cite] are highly successful, they depend on assumed models"
- [DESI, Methods] "The DESI spectroscopic data reduction and redshift measurement pipelines, while extremely efficient, have only been optimized for the classes of objects observed during the main survey."
- [ENC, Data] "the same pre-processed images and spectroscopic redshifts that were used by [Author et al.] … and were generously made publicly available by the authors"
- [RECAL, Introduction] "We use the FlexZBoost [cite] algorithm, which was demonstrated as the best performing photo-$z$ prediction algorithm among the ones compared by [Author et al.], though any machine learning algorithm producing PDFs will suffice."
- [ENC, Introduction] "Template-based methods work well for deep, high redshift surveys where the faintness of the galaxies … However, SED templates often rely on assumptions on galaxy physics"
- [DESI, Discussion] "DESI has significant instrumental advantages for this over DEIMOS"

### E.3 Comparisons are made with paired numbers in parentheses, joined by "vs."
Tier: ALL · Genre: DISTINCTIVE
Evidence:
- [ENC, Results] "Both of them use models with about 3 times as many trainable parameters compared to ours ($\sim$24 million vs $\sim$8 million)."
- [ENC, Results] "photo-$z$ predictions have a lower spread for ellipticals than spirals ($\sigma_{\mathrm{NMAD}}=0.00844$ vs. $0.00956$) with a comparable fraction of outliers (0.18% vs 0.20%)"
- [PENG, Results] "(Pearson $r \sim 0.71$ for both, and normalized RMSE $1.51$ vs. $1.63$ for the baseline)"
- [PRAT, Results] "SCREAM outperforms algorithms like SKYCURTAINS [cite] by 12 percentage points in precision and 28 in recall"
- [DESI, Abstract] "with only $\sim2\times$ longer integration time (rather than $\sim 8\times$ longer as would be expected from aperture-area scaling), while simultaneously achieving $\sim30$ times larger multiplexing"

### E.4 "For example," / "For instance," follows an abstract claim with a concrete case
Tier: ALL · Genre: GENRE
Evidence:
- [ENC, Introduction] "For example, it will be possible to measure spectroscopic redshifts for less than 1% of the galaxies that will be used in the Rubin Observatory"
- [DESI, Discussion] "For instance, even if a galaxy has strong spectral features, those features may be redshifted out of the instrument's observable window."

---

## F. Agency and pronouns

### F.1 "We" performs every author decision; passive is reserved for what instruments, pipelines, or other people did
Tier: ALL · Genre: GENRE
Evidence:
- [DESI, Data] "The observations were conducted using a series of individual exposures … After each exposure, the telescope was dithered by 1.5 arcmin" (instrument) vs "We then selected galaxies that have extinction-corrected $i$-band magnitudes" (authors)
- [DESI, Methods] "Each spectrum was inspected by two volunteers and their scores were averaged." (others) vs "we entirely excluded objects" (authors)

### F.2 Reader-inclusive "us": "gives us", "provides us with", "allows us to", "tells us", "helps us"
Tier: ALL · Genre: DISTINCTIVE
Evidence:
- [RECAL, Re-calibration] "This gives us the relation:"
- [RECAL, Introduction] "The TEDDY data set is divided into four subsets which provide us with a test bed"
- [ENC, Introduction] "also give us an additional piece of information to help break degeneracies"
- [ENC, Results] "This tells us that the capsule dimensions encode and use visual and morphological properties"
- [ENC, Results] "which helps us to qualitatively identify how much the prediction changes"
- [PENG, Introduction] "This allows us to investigate the relationship between star formation and galactic structure"
- [PENG, Results] "The predictions from our method could enable us to examine specific regions within a galaxy"
- [DESI, Discussion] "and thereby connect the observing time invested in a photo-$z$ directly to its impact"

### F.3 "our" attaches to everything the authors made: our data set, our algorithm, our method, our model, our results
Tier: ALL · Genre: GENRE

### F.4 "We note that" is the aside form; "Note that" and "It is worth noting" do not occur
Tier: ALL · Genre: DISTINCTIVE (by contrast)
Evidence:
- [DESI, Discussion] "We note that galaxies for which a reliable redshift measurement could not be obtained with DESI could be followed up"
- [DESI, Discussion] "We also note that DESI itself will be one of the most efficient instruments for obtaining such a sample."
- [DESI, Discussion] "We note that for an LSST Year-1 like analysis, achieving an 80% spectroscopic success rate…"

### F.5 Observed once: third-person "the authors" for the writers themselves
Tier: SINGLE
- [ENC, Training] "can almost always be classified into a spiral or elliptical galaxy by the authors and the predictions of our model for those objects matches with the judgement of the authors"

---

## G. Vocabulary

### G.1 Words that are his, across eras, and must not be scrubbed as AI-isms
Tier: ALL · Genre: DISTINCTIVE (because a de-LLM pass would remove them)
- **leverage**: [DESI, Intro] "by leveraging the capabilities of DESI"; [RECAL, Abstract] "We leverage a recently developed regression technique"; [ENC, Intro] "as they can leverage the pixel level data"
- **utilize**: [DESI, Methods] "we utilize the data to develop a model"; [DESI, Discussion] "The DEEP2/3 pipelines primarily utilized a “local” sky subtraction"; [PRAT, Methods] "We utilize astrometric and photometric data"
- **robust / robustness**: [DESI, Methods] "thanks to the robustness of the median statistic"; [ENC, Intro] "Capsule networks are robust to rotations"; [PENG, Intro] "synthesizes robust representations"
- **crucial**: [DESI, Data] "This capability is crucial, as it enables secure redshift measurements"; [ENC, Intro] "will be crucial to achieve the ambitious science goals"; [RECAL, Intro] "crucial information for many astrophysical studies"; [PENG, Abstract] "offering crucial insights"
- **transformative**: [DESI, Discussion] "would provide a transformative data set to the community"; [DESI, Summary] "would be transformative for cosmology"; [PRAT, Abstract] "the transformative potential"
- **powerful**: [DESI, Discussion] "the instrument's powerful capabilities"; [DESI, Discussion] "a powerful and feasible path"; [PENG, Results] "a powerful inductive bias"
- **very**: [ENC] "very large", "very inefficient", "very misleading", "very small", "very useful", "very good", "very well"; [DESI] "very promising", "very similar", "very small"
- **similar / similarly**: ENC ≈15, DESI ≈12 — "other similar works" ×3, "a similar approach", "similar results"
- **significantly**: see D.6
- **roughly / approximately / about / around / ∼**: all five used interchangeably for approximate numbers — [DESI] "roughly 17,000 sq. degs.", "approximately 94 min", "about 2 hours"; [ENC] "about 1-2%", "around 18%", "roughly the same"; [PENG] "roughly $10^4$ galaxies"

### G.2 Signature phrases
Tier: ALL unless noted · Genre: DISTINCTIVE
- "in a future work" (A.8)
- "(also called X)" (C.2)
- "gives us / provides us with / allows us to / tells us" (F.2)
- "for our purposes" — JOURNAL: [DESI, Data] "For our purposes, we shall refer to the region…"; [DESI, Results] "unreliable for our purposes"; [ENC, Data] "equivalent for our purposes"
- "which we call / hereafter referred to as / (or simply …)" — naming things explicitly: [DESI, Methods] "a new parameter which we call the adjusted magnitude"; [DESI, Discussion] "which we call the “DESI-Deep Survey” hereafter"; [DESI, Data] "hereafter referred to as the “DESI-Deep pilot sample” (or simply the “pilot sample”)"; [DESI, Data] "which we label the DESI-Hercules field"; [ENC, Capsule Networks] "the entire computational chain is termed as a capsule network"
- "This is because" / "This might be because" — JOURNAL (D.2)
- "We first … We then …" (B.4)
- "state-of-the-art" — ENC only (×4 plus caption); absent elsewhere → SINGLE

### G.3 Spelling and compounding follow the venue
Tier: ALL · Genre: GENRE
- ENC (MNRAS) is fully British: colour, optimise, minimise, centred, catalogue, labelled, regulariser, organised, analysing, artefacts. DESI, RECAL, PENG, PRAT are American.
- "data set" (two words) in DESI, ENC, RECAL; "dataset" in PENG, PRAT and mixed within DESI ("a DESI-Deep data set" / "the resulting dataset").
- Plural of symbols with apostrophe: "photo-$z$'s", "spec-$z$'s"; "PDFs" without.

### G.4 Absent in all five
Tier: ALL · Genre: DISTINCTIVE (by absence)
delve, tapestry, underscore, pivotal, landscape, paradigm, holistic, nuanced, intricate, multifaceted, harness, seamless, showcase, "it is worth noting", "it should be noted", "Note that", "Firstly/Secondly", "Overall,", "In summary,", rhetorical questions, exclamation marks, first-person singular, contractions (one "doesn't" in ENC — SINGLE).

---

## H. Punctuation and typography

### H.1 Dashes are rare (≤0.4 per 1000 words) and inconsistently spaced; zero in the 2026 papers
Tier: ALL · Genre: DISTINCTIVE (LLM default is roughly ten times this rate)
Evidence:
- [RECAL, Introduction] "photometric redshifts (photo-$z$'s)---redshifts estimated from imaging alone---will be necessary" (paired, unspaced)
- [ENC, Introduction] "invariant to viewpoint---a useful quality for analysing randomly oriented galaxies"
- [ENC, Training] "We choose the epoch which has the best performance---i.e., the highest classification accuracy"
- [DESI, Discussion] "the two equatorial Rubin Observatory LSST Deep Drilling Fields (DDFs) --- COSMOS and XMM-LSS, as they will" (spaced)
- [DESI, Introduction] "Photometric redshifts (photo-$z$'s) -- i.e., estimates of galaxy redshifts" (double hyphen as dash)
Counts: ENC 4 in 11k words, DESI ≈4 in 11.5k, RECAL 2 in 1.8k, PENG 0, PRAT 0.

### H.2 Semicolons join a clause to its qualification, often carrying "however" / "therefore"
Tier: JOURNAL (DESI ≈4/1k, ENC ≈1.5/1k, workshop papers ≈0) · Genre: UNSURE
Evidence:
- [DESI, Results] "however, this test is limited by their sample that lacks a color selection"
- [DESI, Results] "All DEEP2/3 observations were performed with an on-sky exposure time of approximately 1 hour; therefore we do not bin this sample in time."
- [DESI, Methods] "The spectroscopic pipeline makes assumptions about the intrinsic spectra of galaxies and is optimized for the main survey targets [cite]; we wish to avoid any impact from these assumptions."

### H.3 Colons introduce every display equation
Tier: ALL · Genre: GENRE — see I.1

### H.4 Double quotation marks scare-quote a coined or borrowed term at first use
Tier: ALL · Genre: DISTINCTIVE
Evidence: [DESI] “DESI-Deep pilot sample”, “reliable”, “clean”, “optimal extraction”, “spectro-perfectionism”, “perfect”, “local”, “non-local”, “Field-limited”, “dark years”; [ENC] “confident”, “instantiation parameters”, “probability”, “prediction”; [PRAT] “cocoon”.

### H.5 Parenthetical density is high (8–18 per 1000 words) and parentheses do six jobs
Tier: ALL · Genre: DISTINCTIVE as a density
Glosses (i.e./e.g./also called), acronym-with-citation "(DESI; [Author et al.])", cross-references "(see Sec. [ref])", numeric ranges "(17–308 min)", paired comparisons "(0.18% vs 0.20%)", panel pointers "(top row)", "(Fig. [ref] left column)".

---

## I. Math and figure integration

### I.1 The equation sandwich: "… is given by:" → equation → "where …" → plain-English restatement
Tier: ALL · Genre: GENRE for the sandwich; DISTINCTIVE for the restatement sentence that follows
Pattern: The lead-in ends with a colon after "is given by", "defined as", "can be written as", "we obtain", "such that", "This gives us the relation". The "where" clause names every symbol in order. Then, in the journal and RECAL papers, a sentence says in words what the equation means.
Evidence:
- [RECAL, Re-calibration] "This gives us the relation: ⟨display equation⟩ This means that our corrected PDF equals the initial PDF multiplied by a correction factor which is the local PIT distribution evaluated at the coverage corresponding to various redshifts."
- [DESI, Methods] "we begin by defining a new parameter which we call the adjusted magnitude: ⟨display equation⟩ where $m_i$ is the extinction corrected $i$-band magnitude. This quantity is related to the negative logarithm of the SNR (Eq. [ref]) up to an additive constant."
- [DESI, Methods] "The probability of obtaining a successful redshift measurement is then given by: ⟨display equation⟩ where $\sigma(x)$ is the inverse of the logit function (also called the sigmoid function) and is defined as:"
- [PENG, Methods] "This yields a $\chi^2$-type loss function: ⟨display equation⟩ summed over all image and spectral pixels. The log normalization term penalizes variance inflation where observed data exists."
- [PRAT, Methods] "The likelihood for a single observation is: ⟨display equation⟩ Using Bayes' theorem and assuming a uniform prior over the true features, we obtain: ⟨display equation⟩ where $P(\mathbf{x}_i | \mathbf{x}_i^{\mathrm{true}})$ is the distribution from which our observed features are drawn"
- [ENC, Loss Functions] "where $T_{j}$ represent the class labels and $T_{j}=1$ when a galaxy corresponding to class $j$ is present … The $\lambda$ parameter down-weights the margin loss for an absent morphological class, preventing the lengths of all the capsules from shrinking during the initial learning phase."

### I.2 Symbols are introduced with "Let … be" / "denote" and then used in running prose
Tier: ALL · Genre: GENRE
Evidence:
- [RECAL, Re-calibration] "Let $\widehat{p}(z|\mathbf{x})$ be the initial estimate of the true PDF $p(z|\mathbf{x})$ of the target variable $z$ (redshift) given the input features $\mathbf{x}$ (galaxy colors and magnitudes). The random variable corresponding to $z$ is denoted by $Z$."
- [PENG, Methods] "Let $\mathbf{x}_{\text{obs}}$ denote the observed fluxes with pixel-wise known variances $\boldsymbol{\sigma}_{\text{obs}}^2$."
- [ENC, Appendix] "Let $\mathbf{u}_{i}$ denote the $i^{\mathrm{th}}$ capsule vector in layer $l$ of the network and $\mathbf{v}_{j}$ denote the $j^{\mathrm{th}}$ capsule vectors in layer $l+1$."

### I.3 Captions are complete legends in prose, ending with the takeaway
Tier: ALL · Genre: DISTINCTIVE (length and the closing "We observe that…")
Pattern: Every visual element is named with its colour ("The blue curve shows… the shaded blue region… plotted in orange… The gray line denotes"), then the last sentence states what the reader should conclude. Journal captions run 100–250 words; 2026 captions use "Left Column: (Top) …" labelling.
Evidence:
- [DESI, Captions] "The blue curve shows the success rate obtained from our observations, with the 95% confidence interval shown using the shaded blue region. The success rates as a function of $i$-magnitude for the combined DEEP2 and DEEP3 survey datasets are plotted in orange for comparison … We observe that at exposure times of about 2 hours DESI's success rate matches or exceeds that of the DEEP2 and DEEP3 galaxy redshift surveys."
- [ENC, Captions] "The blue histogram shows the distribution of redshift prediction errors of our algorithm on the test set. The orange line shows a Gaussian distribution … The distribution of the prediction errors is symmetric, centred around 0 and closely resembles a Gaussian distribution, indicating little if any systematic preference for over- or under-estimation."
- [PRAT, Captions] "Top Left ($\phi_2$ vs. $\phi_1$): SCREAM recovers stars along the full spatial extent of GD-1. … False Negatives (green triangles) indicate recall can be improved."

---

## J. Numbers in prose

### J.1 Exact counts wherever they exist; thousands separators from five digits; millions in words
Tier: ALL · Genre: DISTINCTIVE (the precision habit)
Evidence:
- [DESI, Data] "We observed a total of 4863 targets: 3095 in the DESI-XMMLSS field and 1768 in the DESI-COSMOS field."
- [ENC, Data] "This gives us high-quality morphological classifications for 177,442 of the galaxies in our parent data set. We generate morphological class labels for the remaining 339,083 galaxies"
- [PENG, Methods] "The final curated dataset comprises 4.7 million objects, with 98% training, 1% held-out validation for hyperparameter selection, and 1% held-out testing."
- [DESI, Introduction] "obtain spectra for over 60 million galaxies and quasars (compared to the initial forecasts of $\sim$40 million)"

### J.2 A central value is followed by its range in parentheses, and the parentheses are explained once
Tier: JOURNAL · Genre: DISTINCTIVE
Evidence:
- [DESI, Data] "The median effective exposure time was approximately 94 min (17–308 min), with a maximum of 535 min. The numbers in parentheses denote the 5th and 95th percentile values. For the DESI-XMMLSS observations, the median seeing was 1.04 arcsec (0.75–1.24 arcsec)"

### J.3 Results are quoted to the precision of the measurement, and the number comes before the interpretation
Tier: ALL · Genre: GENRE
Evidence:
- [ENC, Results] "our photo-$z$ estimates have $\sigma_{\mathrm{NMAD}}=0.00898$, f$_{\mathrm{outlier}}=0.19\%$ and $\langle \frac{\Delta z}{1+z_{\mathrm{spec}}} \rangle = 7\times10^{-5}$."
- [PRAT, Results] "At a 0.878 confidence threshold, SCREAM achieves an F1 score of 0.66 (Precision: 0.69, Recall: 0.62) against SF labels. Evaluated against true spectroscopic labels, performance improves to an F1 of 0.745"
- [DESI, Results] "$\mathrm{A} = -1.20_{-0.11}^{+.10}$ and $\mathrm{B}= 28.74_{-2.28}^{+2.63}$"

### J.4 Factors and multiples: "a factor of 1.5", "factor of two", "$\sim3\times$", "about 3 times as many"
Tier: ALL · Genre: GENRE

---

## K. Definitions and acronyms

### K.1 Acronym is defined in parentheses with its citation after a semicolon
Tier: ALL · Genre: GENRE (AAS convention) — applied without exception
Evidence: "the Dark Energy Survey (DES; [Author et al.])", "Convolutional Neural Networks (CNNs; [Author et al.])", "(UMAP; [Author et al.])", "(SHAP; [Author et al.])", "(C3R2; [Author et al.])", "Mapping Nearby Galaxies at APO [cite]", "Gaia Data Release 3 (DR3) [cite]"

### K.2 Things are named explicitly and the name is then used
Tier: ALL · Genre: DISTINCTIVE — see G.2 "which we call / hereafter"

---

## L. Absences and refusals

Tier: ALL unless noted.
- No rhetorical questions.
- No one-sentence paragraphs; no paragraph opened with a fragment.
- No sentence-initial "Interestingly". "Importantly" ×1 (RECAL), "Notably" ×1 (PENG caption), "Crucially" ×1 (PRAT abstract) — the last two are 2026.
- No "Note that", "It is worth noting", "It should be noted" — the form is "We note that".
- No bulleted or numbered lists in running prose, except one three-item metric definition (ENC, Results). Procedures are narrated (B.4).
- No em-dash asides at LLM density (H.1).
- No triads for rhythm. Lists are enumerations of however many items there are — often four or five, often closed with "etc.": [DESI, Summary] "excellent throughput, superior astrometry, advanced data processing algorithms, and a dithering strategy"; [ENC, Intro] "morphology, orientation, surface brightness, ratios of magnitudes, or visual appearance in general"; [DESI, Discussion] "seeing, sky transparency, airmass, and Galactic reddening".
- No "Firstly / Secondly / Lastly" as enumeration (one "Lastly," in ENC's roadmap — SINGLE).
- No "In summary" / "Overall". Journal papers use a Summary section; workshop papers end the Results section. "In conclusion," ×1 (PENG, 2026).
- No priority claims ("first", "novel", "to our knowledge") before 2026 (D.5).
- No contractions (one "doesn't", ENC).
- No first-person singular.

---

## Genre baseline

Things the profile must not fight, because the register requires them: funnel introduction (A.2); "However," gap → contribution (A.3); roadmap paragraph in journal papers (A.4); passive for instrument/pipeline actions (F.1); "In this work, we"; equation sandwich with colon and "where" (I.1); "(ACRONYM; citation)" (K.1); British spelling for MNRAS, American for AAS and NeurIPS (G.3); "For example," (E.4); "our data set / our method" (F.3); figure-as-subject openers (A.6).

## Content to quarantine

Subject matter that must not leak into an unrelated paper: photometric redshift / photo-$z$ / spec-$z$ and the apostrophe plurals; DESI, LSST, Rubin, SDSS, HSC-SSP, DEEP2/3, MaNGA, Gaia; "representative spectroscopic samples", "training and calibration", "break degeneracies in the colour–redshift relation", "next-generation imaging surveys", "well-calibrated / locally calibrated PDFs", PIT, capsule, "redshift success rate", "background-limited". Any sentence quoted above is evidence of a *construction*; its nouns are not to be reused.

## Candidate exemplars by section function

Chosen for being typical, not best. Full text is in `scratch/prose/`.

| Slot | Doc, section | First words |
|---|---|---|
| Abstract (journal) | DESI, Abstract | "Deep spectroscopic samples can improve…" |
| Abstract (workshop) | PRAT, Abstract | "Stellar streams are thin, elongated…" |
| Introduction opener | ENC, Introduction ¶1 | "Wide-field extra-galactic sky surveys collect…" |
| Introduction opener (short) | RECAL, Introduction ¶1 | "Galaxy distance, as measured by redshift…" |
| Gap and contribution | DESI, Introduction ¶9–10 | "However, DESI's redshift measurement performance…" |
| Gap and contribution (short) | RECAL, Introduction ¶3–4 | "Several previous works have studied…" |
| Methods, step narration | DESI, Methods "To calculate SNRs" | "To calculate SNRs, we exclusively used…" |
| Methods, step narration with numbers | ENC, Training ¶2 | "We divide the set of 177,442 galaxies…" |
| Pedagogical definition | ENC, Results "distance correlation" | "Since we expect the correlations to be non-linear…" |
| Equation sandwich | RECAL, Re-calibration ¶1–2 | "Let $\widehat{p}(z|\mathbf{x})$ be…" |
| Equation sandwich (model) | DESI, Methods "Modeling the Redshift Success Rate" | "The probability of success calculated from…" |
| Results with comparison | ENC, Results ¶ "When trained on 80%" | "When trained on 80% and tested on 10%…" |
| Results from figure | DESI, Results "Figures [ref] and [ref] demonstrate" | "Figures [ref] and [ref] demonstrate that DESI…" |
| Results (short) | PRAT, Results ¶2 | "At a 0.878 confidence threshold…" |
| Hedged interpretation | ENC, Results "elliptical vs spiral" | "When the test set is split into subsets…" |
| Limitation | DESI, Discussion "It is uncertain" | "It is uncertain which if any of these factors…" |
| Limitation (short) | PRAT, Results ¶3 | "Figure [ref] visualizes the algorithm…" |
| Discussion close | ENC, Summary last ¶ | "More generally, the future of…" |
| Discussion close (short) | RECAL, Results last ¶ | "This work shows that PDFs can be…" |
| Caption | DESI, Captions "Redshift measurement success rate … as a function of $i$-band magnitude" | "Redshift measurement success rate for the DESI-Deep pilot…" |
| Caption (short) | PRAT, Captions ¶2 | "Visualization of SCREAM performance…" |

## Questions for the interview

1. The 2026 papers use "novel", "uniquely", "Crucially,", "This proves that", "for the first time", "transformative potential", "powerful generalization capabilities". The 2021–2024 papers use none of these. Which register is the target — and is the difference the venue, the co-authors, or a change in how you write?
2. Restrictive "which" without a comma (C.6) — keep, or normalise to "that"?
3. "in a future work" with the article (A.8) — keep?
4. "(e.g., X, Y, etc.)" (C.2) — keep?
5. "utilize" vs "use": DESI leans "utilize", ENC leans "use". Preference, or co-author?
6. "data set" vs "dataset"?
7. Sentence-initial bare "This" (B.2) — editors flag it; you use it constantly. Keep?
8. "very" and "significantly" as intensifiers (G.1, D.6) — keep at your rate?
9. Long paragraphs (B.3): 100–330 words in journal papers. Deliberate?
10. Semicolons: DESI uses many, ENC few. Yours, or the senior co-author's?
11. "We see that" as the results-narration verb (A.6) — default, or would you vary it?
12. Which parts of DESI's introduction and discussion are joint with the senior co-author? The extraction cannot tell.
13. The pedagogical definition at first use (A.5) — is that a deliberate stance about who the reader is?
14. Crediting before criticising (E.2) — deliberate?
15. Dashes (H.1): you use almost none. Is that a rule or an accident of typing in LaTeX?
