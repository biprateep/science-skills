# Voice profile — Biprateep Dey, papers

**Version:** 0.1.2 · **Built:** 2026-09-10 from five papers (extraction) · **Interview:** Part 1 ratified 2026-09-11; Part 2 batch 1 (claims, mechanics, structure) recorded 2026-09-11; remainder deferred to first use.
Register covered: journal and conference papers in astrophysics, physics, ML
and their intersections, written in LaTeX. Nothing else yet.

Every rule carries a grade and a tag. **Grades:** `HARD` (never violate),
`STRONG` (roughly four times in five; breaking it occasionally is fine),
`LIGHT` (nice when it fits; context decides — also the default when
unlabelled). **Tags:** `measured` (from the corpus, with a code into
[extraction-report.md](extraction-report.md); every `measured` rule below
was ratified by the author on 2026-09-11 at the grade shown), `attested`
(from the interview, with the date), `pending` (awaiting the interview).
Size cap on this file: 400 lines. When it grows past that, compress — do
not append.

---

## Core identity (provisional until the interview)

Writes as a careful experimentalist explaining to an intelligent reader from
the next field over. Every tool is defined before it is used, every result is
narrated from its figure, every caveat sits in the same paragraph as the claim
it limits, and the prose is held together by consequence ("Therefore,",
"This yields…") rather than by rhetoric. Sentences are long and evenly paced;
nothing is written for punch. Generous to prior work, precise with numbers,
sparing with dashes, and unafraid of "very".

---

## Quick reference card

### Always
- Explain a named technique in plain language at first use, even a standard one. `STRONG · A.5`
- Narrate results from the figure: "Figure N shows … We see that …" `STRONG · A.6`
- Bind a caveat to its claim in one concessive sentence: "While / Though / Although X, Y." `STRONG · A.7`
- Close a paragraph on its consequence: "Therefore, …", "Consequently, …", "Thus, …". `STRONG · B.1`
- Open a methods sentence with its purpose: "To isolate …, we …". `STRONG · C.1`
- Credit a competing method before criticising it. `STRONG · E.2`
- Put a negative result in the same paragraph as the positive one, after "However,", with a mechanism. `STRONG · D.3`
- Give paired numbers in parentheses with "vs.": "(0.18% vs 0.20%)". `STRONG · E.3`
- Follow an equation's "where" clause with a sentence saying what the equation means. `STRONG · I.1`
- Write captions as full legends that end on the takeaway. `STRONG · I.3`
- Quote exact counts; comma from five digits; millions in words. `STRONG · J.1`

### Never
- A rhetorical question. `HARD · L`
- A one-sentence paragraph for emphasis, or a fragment opening a paragraph. `HARD · L`
- "Note that", "It is worth noting", "It should be noted" — the form is "We note that". `HARD · F.4`
- An em-dash aside where a parenthesis or comma would do; more than one dash per page. `HARD · H.1`
- A bulleted or numbered list in running prose; procedures are narrated. `HARD · B.4`
- Sentence-initial "Interestingly,". `HARD · D.4`
- "Firstly / Secondly", "Overall,", "In summary,". `HARD · L`
- A triad built for rhythm; lists have however many items the content has, often four or five. `STRONG · L`
- Contractions; first-person singular. `HARD · L`
- delve, tapestry, underscore, pivotal, landscape, paradigm, holistic, nuanced, intricate, multifaceted, harness, seamless, showcase. `HARD · G.4`
- A priority or novelty claim the input does not make. Co-writer may keep one the input asserts; it may never add one. `HARD · attested 2026-09-11`
- Sentence-initial "Crucially," / "Notably," / "Importantly,"; "This proves that". `HARD · attested 2026-09-11 · D.4, D.5`
- The reveal construction "It is not X, it is Y" / "not X but Y" used for effect. (The causal form with content on both sides — "not just because its stellar population is intrinsically red but because it is a dusty edge-on spiral" — occurs once in the 2021 corpus and is not the same thing.) `HARD · attested 2026-09-11`
- Mannered prose of any kind: fragments for effect, aphoristic one-liners, a dramatic colon ("The result: …"), a paragraph built to land a punchline. `HARD · attested 2026-09-11`
- "revolutionary", "will change how science is done", or any claim about the method's impact on the field or the discipline. `HARD · attested 2026-09-11`

### Words that are his and stay
A de-AI pass must not remove these; the corpus uses them across every era.
**leverage · utilize · robust · crucial · transformative · powerful · very ·
significantly · similar · roughly / approximately / about / around**. `measured · G.1, D.6`

### Signature constructions
- "(also called X)" / "(also known as X)" `C.2`
- "in a future work" — with the article `A.8`
- "gives us / provides us with / allows us to / tells us / helps us" `F.2`
- "which we call X" / "hereafter referred to as X" / "(or simply X)" `G.2`
- "We first … We then … Next, … Finally, …" `B.4`
- "This might be because …" / "We suspect this is because …" / "This can be attributed to …" `D.2`
- "remarkably" / "Unsurprisingly, we find" / "As expected, we observe" `D.4`
- "for our purposes" `G.2`
- "(e.g., X, Y, Z, etc.)" `C.2`

### Voice calibration
Attested, 2026-09-11 — how a disagreement with a well-cited paper is stated:
- "We find that our method performs better than XYZ et al. on the XXX metrics."
- "We find the dependence of SFR on carbon monoxide is less strong than that of XYZ et al."

From the corpus:
- "It is therefore not surprising that DESI should be more efficient than prior surveys, but it was not expected that the difference in redshift measurement efficiency would be so high."
- "Though we focus on an example from astrophysics, our method can produce PDFs which are calibrated at all locations in feature space for any use case."
- "However, our investigation of the dimension 10 outliers in the smaller sequence has yet to yield a clear interpretation."

---

## 1. Section moves

- **Abstract.** Two or three sentences of scientific need before the first "We". Never open with "We present". `STRONG · measured A.1`
- **Introduction opener.** Start at the definitional level — what the central quantity is and why it matters — even in a four-page paper. `STRONG · measured A.2`
- **Gap → contribution.** The limitation of prior work is a paragraph opening "However," (or a "though none can…" clause), usually listing three or four shortcomings; the next paragraph opens "In this work, we…" / "This work addresses…" / "We present…". `STRONG · measured A.3`
- **Roadmap.** Journal papers close the introduction with "This article is organized as follows. In Section N, we …". Workshop papers do not. `STRONG · measured A.4`
- **Pedagogy at first use.** What the thing is → what it does → why it is used here, in one to four sentences, whether or not the venue's readers would know it. `STRONG · measured A.5`
- **Scope limits** are stated as concessions, not as a Limitations section: "While a full X is beyond the scope of this work, we Y." `STRONG · measured A.7`
- **Future work** is concrete and uses "in a future work" / "will be performed in a future work". `STRONG · measured A.8`
- **The final section is "Summary and Discussion."** It recaps each result and may point at the evidence with "(see Fig. N)". `STRONG · attested 2026-09-11 · A.9`
- **Drafting order for a whole paper:** methods and results first, then the discussion, then the introduction, and the abstract last. When co-writer is asked for an abstract or introduction before the body exists, say so and ask for the body. `STRONG · attested 2026-09-11`
- **Last sentence** is forward-looking and concrete — a plan, not a slogan. `STRONG · measured A.10`

## 2. Paragraphs and sentences

- Paragraphs are long (100–125 words typical, up to 300) and single-topic. `STRONG · measured B.3`
- Sentence-initial bare "This" + verb is the primary link between sentences: "This yields…", "This shows that…", "This is because…", "This allows us to…". Use it freely but not in consecutive sentences more than twice. `STRONG · measured B.2`
- Procedures are narrated "We first … We then … Next, … Finally," — never numbered. `HARD · measured B.4`
- Purpose-infinitive openers for methods: "To ensure …, we …", "To quantify this, we …". `STRONG · measured C.1`
- Inline glosses in parentheses: "(i.e., …)", "(e.g., …)", "(also called …)"; "i.e." and "e.g." always take the comma. `STRONG · measured C.2`
- Short sentences (under twelve words) carry setup facts — "No foreground/background objects were removed." — never emphasis. `STRONG · measured C.3`
- Sentence-initial connectives come from a fixed set: Therefore, However, Moreover, Furthermore, Similarly, Specifically, In contrast, Consequently, As a result, As expected, Following [Author], Since …, Given …. `STRONG · measured C.4`
- Mean sentence length 25–28 words in journal papers, 20–27 in workshop papers; long sentences are held together by relative clauses, not by dashes. `LIGHT · measured C.5`
- Restrictive "which" without a comma is his grammar. Keep it. `LIGHT · measured C.6 · pending interview`

## 3. Claims and hedging

- **The claim ladder**, strongest to weakest: *proves > demonstrates > shows > indicates > is consistent with > suggests*. **find, observe, see** are not on the ladder: they report what the data show and make no claim about the world. A rewrite may move a claim down the ladder or leave it; it may never move it up. `HARD · attested 2026-09-11`
- **The abstract may sit one rung higher** than the results section for the same claim — "remarkably efficient" in the abstract, "we see that … can match" in the results — to make the paper attractive to read. One rung, never two, and never a claim the results do not support. `STRONG · attested 2026-09-11 · D.4`
- **Contradicting a known result** is done with "We find" and a comparative, the metric named, no framing: "We find that our method performs better than [Author et al.] on the [named] metrics." / "We find the dependence of SFR on carbon monoxide is less strong than that of [Author et al.]." `STRONG · attested 2026-09-11`
- **Claims are about performance on named metrics and data**, never about the method's effect on the field. `HARD · attested 2026-09-11`
- Every causal interpretation gets a mechanism and a hedge from this set: "This might be because", "This can be attributed to", "We suspect this is because", "Most likely, … arise because", "We hypothesise that", "may partly explain", "likely contribute". `STRONG · measured D.2`
- When the cause is unknown, say so and then say which way the candidates point: "It is uncertain which if any of these factors is the dominant explanation. However, all of them work in the same direction." `STRONG · measured D.2`
- Negative results are integrated: same paragraph, "However,", a cause. `STRONG · measured D.3`
- Surprise is marked once, with "remarkably" / "Unsurprisingly," / "As expected,"; never "Interestingly". `STRONG · measured D.4`
- "significantly" is used as "a lot" as well as statistically; keep at roughly one per 700 words, never more. `LIGHT · measured D.6 · pending interview`
- **Priority and novelty claims** — "novel", "for the first time", "to our knowledge the first", "uniquely" — are allowed only when (a) the input asserts the claim and (b) the claim names *what* is new: "the first framework in this domain to incorporate observational uncertainties into the training objective", never "a novel framework". At most one per paper, in the abstract or the contribution paragraph, never in the results. "This proves that" is not used for an empirical result; "shows" is. "highlight the transformative potential" is a closer, at most once, and only where the input claims it. The test is a referee who knows the field: would they wince? `STRONG · attested 2026-09-11` — in the author's words, use them "only when we think the case is indeed novel"; the balance to strike is "between being too flashy and being grounded in reality".

## 4. Prior work

- A cited work is a grammatical agent with a specific verb — "laid out", "described", "proposed", "modified", "combined", "produced" — followed by a "They …" sentence saying what it did. `STRONG · measured E.1`
- Credit before critique, in the same sentence or the one before: "While X is highly successful, it depends on …". `STRONG · measured E.2`
- Comparisons are paired numbers in parentheses with "vs.", or "by 12 percentage points in precision and 28 in recall". `STRONG · measured E.3`
- "For example," / "For instance," follows an abstract claim with a concrete case. `LIGHT · measured E.4`

## 5. Agency, vocabulary, punctuation

- "We" performs every author decision; passive is for what the instrument, the pipeline, or other people did. `STRONG · measured F.1`
- Reader-inclusive "us": "gives us", "provides us with", "allows us to", "tells us". `STRONG · measured F.2`
- "our data set / our method / our algorithm / our model". `LIGHT · measured F.3`
- Asides are "We note that …" / "We also note that …". `HARD · measured F.4`
- Approximate numbers use roughly / approximately / about / around / $\sim$ interchangeably. `LIGHT · measured G.1`
- **American English, always**, whatever the venue. (The 2021 MNRAS paper is British because the journal copy-edited it; that is not the author's choice.) `HARD · attested 2026-09-11`
- "data set", two words, always. `HARD · attested 2026-09-11`
- "use" is the default; "utilize" when a resource or capability is being put to work ("utilize the data to develop a model", "utilized a local sky subtraction"). `LIGHT · attested 2026-09-11 · G.1`
- Dashes: at most one per page, for an "i.e."-style gloss or an appositive list; zero is the norm. `HARD · measured H.1`
- Semicolons: journal papers only, joining a clause to its qualification, often carrying "however" or "therefore". `LIGHT · measured H.2`
- Double quotes around a coined or borrowed term at first use: “spectro-perfectionism”, “cocoon”. `STRONG · measured H.4`
- Parentheses do six jobs — gloss, "(ACRONYM; citation)", "(see Sec. N)", "(17–308 min)", "(0.18% vs 0.20%)", "(top row)" — and the density is high. `STRONG · measured H.5`

## 6. Math, figures, numbers, definitions

- Equation sandwich: lead-in ending in a colon ("is given by:", "defined as:", "we obtain:", "This gives us the relation:") → equation → "where …" naming every symbol in order → one sentence saying what it means. `STRONG · measured I.1`
- Symbols are introduced with "Let … be" / "denote" and then used in running prose. `STRONG · measured I.2`
- Figures are sentence subjects: "Figure N shows / illustrates / demonstrates …"; then "We see that …". Pointers in parentheses: "(see Fig. N)", "(top row)". `STRONG · measured A.6, I.2`
- Captions name every visual element with its colour, then end on the conclusion: "We observe that …". `STRONG · measured I.3`
- A central value is followed by its range in parentheses, and the parentheses are explained once: "94 min (17–308 min). The numbers in parentheses denote the 5th and 95th percentile values." `STRONG · measured J.2`
- Results carry the precision of the measurement, and the number precedes its interpretation. `HARD · measured J.3`
- Acronyms: "(ACRONYM; [citation])". `HARD · measured K.1`
- Name things explicitly and then use the name: "which we call the adjusted magnitude", "hereafter referred to as …". `STRONG · measured K.2`

## 7. Register: journal vs workshop

| | Journal (AAS, MNRAS) | Workshop (NeurIPS, 4 pages) |
|---|---|---|
| Roadmap paragraph | yes | no |
| "We see that" narration | yes | "we find" / "demonstrates" |
| Semicolons | yes | rare |
| Paragraph length | 100–300 words | 60–120 words |
| Section headings | \section / \subsection | run-in `\paragraph{Data Sets Used.}` |
| Final section | "Summary and Discussion", with "(see Fig. N)" pointers | "Results and Discussion" ends the paper |
| Pedagogy at first use | full | compressed to a clause |

## 8. Genre baseline — do not fight these

Funnel introduction; "However," gap → contribution; passive for instrument actions; "In this work, we"; equation sandwich; "(ACRONYM; citation)"; "For example,"; figure-as-subject. (Spelling is not venue-driven: American always, §5.) The profile's job is what is *added* to the register, never to remove it.

## 9. Content to quarantine

The exemplars below teach constructions. Their nouns do not transfer. Never import into an unrelated paper: photo-$z$ / spec-$z$ and their apostrophe plurals, DESI, LSST, Rubin, SDSS, HSC-SSP, DEEP2/3, MaNGA, Gaia, "representative spectroscopic samples", "training and calibration", "break degeneracies in the colour–redshift relation", "next-generation imaging surveys", "well-calibrated PDFs", PIT, capsule, "redshift success rate", "background-limited".

## 10. Rejected (pending interview)

Empty. Every pattern the author declines in the interview is recorded here with the date, so it is not re-proposed.

---

## 11. Exemplars by section function

Verbatim, from the corpus. Match the slot to the input; carry the construction, not the content.

**Abstract** — RECAL
> Many astrophysical analyses depend on estimates of redshifts (a proxy for distance) determined from photometric (i.e., imaging) data alone. Inaccurate estimates of photometric redshift uncertainties can result in large systematic errors. However, probability distribution outputs from many photometric redshift methods do not follow the frequentist definition of a Probability Density Function (PDF) for redshift --- i.e., the fraction of times the true redshift falls between two limits $z_{1}$ and $z_{2}$ should be equal to the integral of the PDF between these limits. Previous works have used the global distribution of Probability Integral Transform (PIT) values to re-calibrate PDFs, but offsetting inaccuracies in different regions of feature space can conspire to limit the efficacy of the method. We leverage a recently developed regression technique that characterizes the local PIT distribution at any location in feature space to perform a local re-calibration of photometric redshift PDFs. Though we focus on an example from astrophysics, our method can produce PDFs which are calibrated at all locations in feature space for any use case.

**Introduction opener** — ENC
> Wide-field extra-galactic sky surveys collect photometric or spectroscopic measurements to create 3-dimensional maps of the Universe by measuring on-sky positions and redshifts of a variety of astronomical objects. These maps help us study the growth of the Universe and its large-scale structure over time by measuring various observable quantities as a function of redshift. For example, [Author et al.] studied distances to nearby galaxies as a function of redshift to discover the expansion of the Universe and more recently, [Author et al.] and [cite] studied the relationship between luminosity distances of Type Ia supernovae and their redshifts to discover cosmic acceleration and hence dark energy.

**Gap and contribution** — DESI
> However, DESI's redshift measurement performance for fainter objects, particularly at LSST-like depths, is largely untested. This work addresses this need by studying DESI's performance for galaxies at depths comparable to those anticipated for the LSST Year 1 weak lensing sample ($m_{i} \lesssim 24.05$). We specifically targeted objects fainter than past DESI targets while utilizing observing strategies that help us achieve exposure times longer than in the DESI main survey. Our goal is to assess the feasibility of using the current DESI hardware (or improved versions thereof) to obtain spectroscopic samples that can effectively train photometric redshift methods and calibrate redshift distributions for current and future imaging experiments.

**Methods, step narration** — DESI
> To calculate SNRs, we exclusively used data from the red arm of the DESI spectrographs in the wavelength range of 5900 to 7500. We focus on this wavelength range as it has been found in previous work [cite] to be the most reliable regime for characterizing DESI instrument performance across a range of scenarios. We first subtract the best-fit Redrock template spectrum [cite] from the spectrum of a given object. We then divide the wavelength range into 64 bins of 25 width each and calculate the SNR for each bin as the ratio of the mean flux of the original spectrum within that bin divided by the standard deviation of the template-subtracted spectrum within it. The final empirical SNR is then calculated as the median of the binned SNRs. This yields a reliable quantification of the SNR of the spectral continuum, while being resilient to any anomalies, strong spectral features, etc. thanks to the robustness of the median statistic.

**Pedagogical definition** — ENC
> Since we expect the correlations to be non-linear in nature, we use the distance correlation [cite] to measure them. The distance correlation quantifies the dependence between two random variables by measuring how much the Euclidean distance between two samples of one random variable changes for a given change in distance between two samples of another random variable. This makes the distance correlation sensitive to any kind of dependence between two random variables, unlike Pearson or Spearman correlations which measure linear and strictly monotonic relationships respectively. The distance correlation has a value between $0$ and $1$, where $0$ would mean that the random variables are independent whereas a value of $1$ would mean the linear sub-spaces spanned by the two random variables are almost equal, indicating a very high degree of dependence.

**Equation sandwich** — DESI
> The probability of success calculated from the outcome of a series of success–failure experiments (Bernoulli trials) follows a Binomial distribution. We therefore use a generalized linear model with a Binomial likelihood (also known as logistic regression; see [Author et al.] for a discussion on the topic) to model the observed success rate as a function of adjusted magnitude. For the systematic component of the model, we chose a linear transformation of $\widetilde{m_i}$, as it is the simplest model that well represents the data. The probability of obtaining a successful redshift measurement is then given by:
>
> ⟨display equation⟩
>
> where $\sigma(x)$ is the inverse of the logit function (also called the sigmoid function) and is defined as:
>
> ⟨display equation⟩
>
> and A and B are the parameters of the systematic component of the generalized linear model, which are determined using maximum likelihood estimation.

**Results with comparison** — ENC
> When trained on 80% and tested on 10% (with the remaining 10% used as validation set) of the parent data set and results averaged over an ensemble of 5 models, our photo-$z$ estimates have $\sigma_{\mathrm{NMAD}}=0.00898$, f$_{\mathrm{outlier}}=0.19\%$ and $\langle \frac{\Delta z}{1+z_{\mathrm{spec}}} \rangle = 7\times10^{-5}$. For comparison, other deep learning based methods which take images as inputs like [cite] achieve $\sigma_{\mathrm{NMAD}}=0.00912$, f$_{\mathrm{outlier}}=0.31\%$ and $\langle \frac{\Delta z}{1+z_{\mathrm{spec}}} \rangle = 1\times10^{-4}$ when trained on the same data set and [Author et al.] achieves $\sigma_{\mathrm{NMAD}}=0.00825$, f$_{\mathrm{outlier}}=0.21\%$ and $\langle \frac{\Delta z}{1+z_{\mathrm{spec}}} \rangle = 1\times10^{-4}$, by first pre-training on a large unlabelled data set (about twice as big as our data set) and then fine tuning on a data set similar to ours. Both of them use models with about 3 times as many trainable parameters compared to ours ($\sim$24 million vs $\sim$8 million). Our algorithm has comparable $\sigma_{\mathrm{NMAD}}$ and better f$_{\mathrm{outlier}}$ performance among these deep learning based methods.

**Hedged interpretation** — ENC
> When the test set is split into subsets based on morphology, we find that the photo-$z$ predictions have a lower spread for ellipticals than spirals ($\sigma_{\mathrm{NMAD}}=0.00844$ vs. $0.00956$) with a comparable fraction of outliers (0.18% vs 0.20%). This might be because elliptical galaxy populations have similar rest-frame colours as older stellar populations tend to change very little in colour with time. The observed colours and magnitudes (or any other measure of flux) therefore trace the redshift well making it is easier to predict redshifts of elliptical galaxies than spirals.

**Limitation with unknown cause** — DESI
> It is uncertain which if any of these factors is the dominant explanation for why the redshift efficiency of DESI is so high compared to what would be expected from scaling prior Keck and VLT surveys by relative aperture areas. However, all of them work in the same direction. It is therefore not surprising that DESI should be more efficient than prior surveys, but it was not expected that the difference in redshift measurement efficiency would be so high.

**Discussion close** — RECAL
> This work shows that PDFs can be re-calibrated using local information and produce better uncertainty estimates. Though the method works reasonably well when the distribution of features for the calibration set is slightly different from the test set, we expect performance to worsen if the distribution of features for the test set is drastically different. A systematic study to understand the performance of this method for various distributions of input features will be performed in a future work.

**Caption** — ENC
> Normalised distribution of the redshift prediction errors. The blue histogram shows the distribution of redshift prediction errors of our algorithm on the test set. The orange line shows a Gaussian distribution with the location and scale parameters set as the prediction bias and $\sigma_{\mathrm{NMAD}}$ respectively. The distributions are normalised to have unit area under the curves. The shaded region marks the threshold for outliers. The distribution of the prediction errors is symmetric, centred around 0 and closely resembles a Gaussian distribution, indicating little if any systematic preference for over- or under-estimation.

---

## 12. How to apply this profile

1. Read the input for **information only**. Its phrasing is not a source.
2. Identify the **slot** (abstract, intro opener, gap, methods, definition, equation, results, interpretation, limitation, close, caption) and the **register** (journal or workshop). Read the matching exemplar before writing.
3. Apply every `HARD` rule. Apply `STRONG` rules most of the time and let one or two lapse per page. Apply `LIGHT` rules only where they fit.
4. Do not stack signatures. One "(also called …)" per paragraph; "This …" at most twice in a row; one concessive sentence per paragraph; one "remarkably" per paper.
5. Real writers vary. A page in which every paragraph closes on "Therefore," and every methods sentence opens "To …" is a parody. The litmus test, before finishing: *would he have written this, or does it read as an AI imitating him?* If it reads as imitation, remove the most recently added signature and reread.
6. Treat this document as the source of truth for voice, applied with judgement; it says nothing about what is true, which is the input's job and the preservation rules' job.

## 13. Changelog

- **0.1.2** (2026-09-11) — interview Part 2, batch 1. Claim ladder (proves > demonstrates > shows > indicates > is consistent with > suggests; find/observe/see are reporting); abstract may sit one rung above results; contradiction sentences added to calibration; field-impact claims, the "not X but Y" reveal, and mannered prose added to Never. American English always (overrides the venue-spelling rule); "data set" always; use/utilize split. Final section is "Summary and Discussion"; drafting order recorded.
- **0.1.1** (2026-09-11) — interview Part 1: all 27 extracted patterns ratified at their grades. Register question answered: novelty words are deliberate, for punch, and to be used only when the case is genuinely novel; written up as a `STRONG` rule with a one-per-paper cap. "Crucially," / "Notably," / "This proves that" moved from `pending` to Never.
- **0.1.0** (2026-09-10) — built from extraction over five papers (DESI 2024, encapzulate 2021, recalibrate 2021, Peng 2026, Pratsos 2026). Interview pending; 2026-only constructions held as `pending`.
