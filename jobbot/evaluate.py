from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Any
from .normalize import clean_text, normalize
from .rules import (
    CORE_DOMAINS, ADJACENT_DOMAINS, DISTANT_DOMAINS, JOB_FAMILIES,
    DIRECT_EXPERIENCE_SIGNALS, METHOD_SIGNALS, HARD_BLOCKERS,
    SPECIALIST_ACADEMIC_GAPS, TITLE_DISTANT_PATTERNS,
)


@dataclass
class Evaluation:
    score: int
    recommendation: str
    domain_category: str
    job_family: str
    fit_signals: list[str]
    partial_matches: list[str]
    missing_requirements: list[str]
    blockers: list[str]
    reason: str

    def to_dict(self):
        return asdict(self)


def _matches(text: str, mapping: dict[str, list[str]]) -> list[str]:
    out = []
    for name, patterns in mapping.items():
        if any(re.search(p, text, re.I) for p in patterns):
            out.append(name)
    return out


def _domain_relevant_text(text: str) -> str:
    t = normalize(text)
    noise_patterns = [
        r"(?:equal opportunity employer|we are an equal opportunity employer).{0,700}",
        r"(?:without regard to|regardless of).{0,450}(?:race|color|colour|religion|gender|sex|sexual orientation|disability|veteran|marital status).{0,450}",
        r"\bdisability status\b",
        r"\bexercise (?:your|their|his|her|the) (?:data[- ]protection )?rights\b",
        r"\bmental health support\b",
        r"\bmental health resources\b",
        r"\bmental health benefits?\b",
        r"\bhealth(?:care)? insurance\b",
        r"\bwellness benefits?\b",
        r"\bwellbeing benefits?\b",
        r"\bspanish public health and social security system\b",
        r"\bpublic health and social security system\b",
        r"\bfunctional capacity to (?:perform|carry out) (?:the )?duties\b",
        r"\bfunctional capacity for (?:the )?performance of (?:the )?duties\b",
        r"\bpriority will be given to (?:people|persons|candidates) with disabilit(?:y|ies)\b",
        r"\b(?:people|persons|candidates) with disabilities? (?:will )?(?:have|receive) priority\b",
        r"\bdisability quota\b",
        r"\b(?:people|persons|candidates) with disabilities? (?:greater than|above|over) \d+(?:\s*percent)?\b",
        r"\bdisabilit(?:y|ies).{0,40}(?:quota|reserve|priority|legal requirement|employment policy)\b",
    ]
    for pattern in noise_patterns:
        t = re.sub(pattern, " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def detect_domain(text: str) -> tuple[str, list[str], list[str]]:
    text = _domain_relevant_text(text)
    core = _matches(text, CORE_DOMAINS)
    adjacent = _matches(text, ADJACENT_DOMAINS)
    distant = _matches(text, DISTANT_DOMAINS)
    if core:
        return "CORE", core, distant
    if adjacent:
        return "ADJACENT", adjacent, distant
    if distant:
        return "DISTANT", [], distant
    return "UNCLEAR", [], []


def detect_family(title: str) -> tuple[str, list[str]]:
    t = normalize(title)
    for family, patterns in JOB_FAMILIES.items():
        matched = [p for p in patterns if re.search(p, t, re.I)]
        if matched:
            return family, matched
    return "unclear", []


def location_points(job: dict[str, Any], text: str) -> tuple[int, list[str], list[str]]:
    location = normalize(job.get("location", ""))
    modality = normalize(job.get("modality", ""))
    combined = f"{location} {modality} {normalize(text)}"
    good, partial = [], []

    if "spain" in combined or any(x in combined for x in ["barcelona", "madrid", "valencia", "sevilla", "seville", "malaga", "bilbao", "zaragoza", "granada", "lleida", "girona", "tarragona"]):
        good.append("Location compatible with Spain target")
        return 5, good, partial

    remote_eu = bool(re.search(r"remote.{0,30}(europe|eu)|europe.{0,30}remote|eu.{0,30}remote", combined, re.I))
    if remote_eu:
        if re.search(r"(?:must|required|only).{0,50}(?:reside|resident|work authorization|based in).{0,50}(france|germany|italy|netherlands|belgium|portugal|ireland|uk|united kingdom)", combined, re.I):
            partial.append("Remote Europe role may require residence/work authorization outside Spain")
            return 1, good, partial
        good.append("Remote Europe/EU; no explicit exclusion of working from Spain detected")
        return 4, good, partial

    if re.search(r"remote", combined, re.I):
        partial.append("Remote location is ambiguous; verify Spain eligibility")
        return 3, good, partial

    partial.append("Outside-Spain or unclear location")
    return 0, good, partial


def _specialist_method_gaps(text: str) -> list[str]:
    """Detect specialist method stacks that are not evidenced in the CV.

    A single lab keyword is not enough. We require a cluster of role-defining methods,
    which avoids penalising broad biomedical descriptions while catching highly
    specialised wet-lab/core-facility posts.
    """
    t = normalize(text)
    groups = {
        "cell_signaling_wet_lab": [
            r"cell signaling|signal transduction|kinase", r"mass spectrom|phosphoproteom",
            r"confocal microscop", r"mammalian cell culture|cell culture", r"phosphomutant",
        ],
        "biomarker_core_facility_lab": [
            r"protein expression", r"immunoassay", r"biomarker quantification|biomarker measurement",
            r"molecular biology", r"biological samples?", r"cell culture|pcr",
        ],
        "clinical_translational_lab": [
            r"clinical or translational laboratory|clinical laboratory", r"supports? diagnosis|diagnostic",
            r"chain of custody", r"lims", r"sample reception|sample tracking|sample manipulation",
        ],
        "molecular_neuromuscular_lab": [
            r"cell culture", r"(?:western blot|immunoprecipitation|\bpcr\b|cloning)",
            r"(?:electron|confocal|advanced optical) microscopy", r"electrophysiological recordings?",
            r"cell and molecular biology techniques?",
        ],
        "immune_cell_wet_lab": [
            r"cell culture", r"flow cytometr", r"biological samples?|serum|ficoll",
            r"macrophage|monocyte|innate immune", r"immunomodulatory",
        ],
        # Coherent specialist stacks below are intentionally multi-signal. They represent
        # role-defining technical profiles not evidenced in the target CV; a single keyword
        # never triggers the gap.
        "patch_clamp_electrophysiology": [
            r"patch[- ]clamp", r"electrophysiolog", r"single[- ]cell|hair cells?",
            r"demonstrated strength|strong (?:experience|expertise)|hands[- ]on|essential|required",
        ],
        "thermochemical_process_engineering": [
            r"chemical looping|thermochemical", r"pyrolysis|gasification",
            r"chemical engineering|process engineering", r"pilot|scale[- ]up|industrial scale",
        ],
        "soil_microbiome_machine_learning": [
            r"soil health|soil science|crop productivity|horticultur",
            r"microbiome|metagenom|metabarcod", r"machine learning|predictive model",
        ],
        "computational_ai_specialist": [
            r"computer vision|vision[- ]language|foundation models?", r"deep learning|machine learning",
            r"python|pytorch|tensorflow", r"computational pathology|medical image analysis",
        ],
        "microbiology_biofilm_specialist": [
            r"bacterial biofilm|biofilm models?", r"mic/m b c|mbec|time[- ]kill|antimicrobial efficacy",
            r"bsl[- ]?2|antibiotic[- ]resistant", r"confocal.*microscop|cell culture",
        ],
        "proteomics_bioinformatics_specialist": [
            r"proteomics?", r"bioinformatic", r"mass spectrom|multiomics?", r"artificial intelligence|machine learning",
        ],
        "molecular_modelling_computational_biology": [
            r"molecular model|molecular dynamics|coarse[- ]grained simulation",
            r"\bamber\b|\bgromacs\b",
            r"high[- ]performance computing|\bhpc\b|linux[- ]based",
            r"python|bash|scientific programming",
            r"structural bioinformatic|alphafold",
        ],
        "advanced_therapies_atmp": [
            r"advanced therapy medicinal products?|\batmp\b|advanced therapies platform",
            r"gene therapy|gene editing|cell[- ]based therap|cell therapy|immunotherapy",
            r"\bgmp\b|viral vectors?|crispr|stem cell biology|immune cell engineering",
            r"regulatory science|clinical translation",
        ],
        "genomic_bioinformatics_specialist": [
            r"genomic data|genomics?|genomic[- ]phenotypic|genomic biomarkers?",
            r"bioinformatic",
            r"integrat(?:e|ion).{0,80}genomic.{0,80}clinical|genomic.{0,80}clinical data",
            r"genetic biomarkers?|genome[- ]wide",
        ],
        "computational_neuroimaging_specialist": [
            r"whole[- ]brain model|brain modelling|modelizacion de cerebro completo|modelitzacio de cervell complet",
            r"neuroimaging preprocess|preprocesamiento de neuroimagen|preprocess.{0,40}(?:mri|fmri|neuroimaging)",
            r"statistical physics|fisica estadistica",
            r"computational neuroscience|neurociencia computacional",
            r"machine learning|artificial intelligence",
            r"matlab|python",
        ],
        "thermoelectric_materials_specialist": [
            r"thermoelectric", r"device fabrication", r"materials? (?:science|physics)|solid[- ]state",
        ],
    }
    gaps = []
    thresholds = {
        "clinical_translational_lab": 2,
        "patch_clamp_electrophysiology": 3,
        "soil_microbiome_machine_learning": 3,
        "molecular_modelling_computational_biology": 3,
        "advanced_therapies_atmp": 3,
        "genomic_bioinformatics_specialist": 2,
        "computational_neuroimaging_specialist": 3,
        "thermoelectric_materials_specialist": 2,
    }
    for name, patterns in groups.items():
        hits = sum(bool(re.search(p, t, re.I)) for p in patterns)
        threshold = thresholds.get(name, 3)
        if hits >= threshold:
            # Patch-clamp is only a gap when it is role-defining/required, not when
            # mentioned incidentally in a broad methods list.
            if name == "patch_clamp_electrophysiology" and not re.search(
                r"(?:demonstrated strength|strong (?:experience|expertise)|hands[- ]on|required|essential).{0,80}patch[- ]clamp|"
                r"patch[- ]clamp.{0,80}(?:required|essential|demonstrated|strong|hands[- ]on)",
                t, re.I
            ):
                continue
            gaps.append(name)
    return gaps


def _mandatory_experience_gaps(text: str) -> list[str]:
    """Detect explicit prior-experience requirements that define a specialist role.

    The detector is intentionally narrow: generic mentions of clinical trials, eCRFs,
    monitoring or GCP are not enough. It requires an explicit minimum/required prior
    experience statement plus a regulated-trial operations stack. This prevents an
    academic human-RCT background from being treated as equivalent to prior sponsor/CRO
    trial-operations experience.
    """
    t = normalize(text)
    gaps: list[str] = []

    explicit_prior_trial_experience = bool(re.search(
        r"(?:at\s+minimum(?:\s+of)?|minimum(?:\s+of)?|at\s+least)\s*(?:\d+(?:\.\d+)?\s*(?:months?|years?))?.{0,100}(?:experience|worked).{0,160}(?:clinical trials?|oncology trials?|hematology trials?|haematology trials?|phase\s*[i1v]+)"
        r"|(?:required|mandatory|essential|must have).{0,120}(?:experience|background).{0,140}(?:clinical trials?|oncology trials?|hematology trials?|haematology trials?|phase\s*[i1v]+)",
        t, re.I
    ))

    regulated_ops_signals = [
        bool(re.search(r"phase\s*(?:i|ii|iii|1|2|3)(?:\s*[,/&-]\s*(?:i|ii|iii|1|2|3))*", t, re.I)),
        bool(re.search(r"\bsponsors?\b|\bcros?\b|contract research organi[sz]ation", t, re.I)),
        bool(re.search(r"\bsae\b|serious adverse event|case report form|\bcrf\b|\becrf\b", t, re.I)),
        bool(re.search(r"monitoring visits?|audits?|inspections?|good clinical practice|\bgcp\b", t, re.I)),
        bool(re.search(r"oncology|ha?ematology|cancer clinical trials?", t, re.I)),
    ]

    # English/Spanish/Catalan research-centre adverts often express the same
    # requirement without a numeric minimum (e.g. "Experience and knowledge:
    # Required: Experience in clinical trials" or "experiència prèvia en la
    # coordinació d'assaigs clínics"). Treat this as specialist trial-operations
    # experience only when it co-occurs with an operational stack.
    explicit_required_trial_ops = bool(re.search(
        r"experience and knowledge.{0,120}required.{0,500}experience.{0,80}clinical trials?"
        r"|(?:experiencia|experiencia previa|experiència|experiencia previa).{0,120}(?:coordinacion|coordinacio|gestion|gestio).{0,120}(?:ensayos clinicos|assaigs clinics|assajos clinics|clinical trials?)"
        r"|(?:required|requisit|required experience|perfil que buscamos|perfil que busquem).{0,240}(?:experience|experiencia|experiència).{0,120}(?:clinical trials?|ensayos clinicos|assaigs clinics)",
        t, re.I
    ))

    if (explicit_prior_trial_experience or explicit_required_trial_ops) and sum(regulated_ops_signals) >= 2:
        gaps.append("regulated_clinical_trial_operations_experience")

    # Hospital clinical-data / REDCap / sample-logistics roles are materially different
    # from academic human-intervention studies. Require a coherent stack before flagging.
    clinical_data_ops_signals = [
        bool(re.search(r"clinical data.{0,80}hospital|datos clinicos.{0,80}hospital|dades cliniques.{0,80}hospital", t, re.I)),
        bool(re.search(r"\bredcap\b|electronic data capture|\bedc\b", t, re.I)),
        bool(re.search(r"biological samples?|muestras biologicas|mostres biologiques", t, re.I)),
        bool(re.search(r"informed consent|consentimiento informado|consentiment informat", t, re.I)),
        bool(re.search(r"patient identification|inclusion of patients|identificacion e inclusion de pacientes|identificacio i inclusio de pacients", t, re.I)),
    ]
    prior_clinical_data_experience = bool(re.search(
        r"(?:experience|experiencia|experiència).{0,120}(?:clinical research|investigacion clinica|recerca clinica|translational research|investigacion traslacional|recerca translacional)",
        t, re.I
    ))
    if prior_clinical_data_experience and sum(clinical_data_ops_signals) >= 3:
        gaps.append("hospital_clinical_data_operations_experience")

    # Research grant/post-award finance is a specialist administrative track when
    # a minimum multi-year background in budgets, justifications and audits is required.
    if re.search(
        r"(?:minimum|at least|al menos|minima|minim).{0,30}(?:2|3|4|5)\s*years?.{0,180}(?:grant|fellowship|research project|ayudas|ajuts|becas).{0,180}(?:financial|economic|administrative|economica|administrativa|pressupost|presupuesto)"
        r"|(?:experiencia minima|experiència minima).{0,40}(?:2|3|4|5)\s*(?:anos|anys|years).{0,220}(?:gestion economica|gestio economica|administrative management|post[- ]award|justificacion|justificacio)",
        t, re.I
    ):
        gaps.append("research_grant_financial_management_experience")

    # Pre-award grant-office roles can require specialist support-side experience that is
    # not equivalent to having written or won grants as a researcher/PI. Require a narrow
    # co-occurrence of explicit researcher-support experience and budget-preparation expertise.
    if (
        re.search(r"proven experience.{0,160}supporting researchers.{0,160}(?:preparing|preparation).{0,100}(?:applications?|proposals?)", t, re.I)
        and re.search(r"expertise.{0,100}budget preparation|budget preparation.{0,100}expertise", t, re.I)
    ):
        gaps.append("preaward_grant_operations_experience")

    # Some public-research recruitment calls separate ordinary scored merits from an explicit
    # minimum "criterio de suficiencia". When the minimum is attached specifically to prior
    # work in an R&D/research-project-management department, it functions as an eligibility
    # threshold rather than a merely desirable merit. Keep this narrow: generic merit tables,
    # Fundanet experience points, or optional EU-project experience do not trigger it.
    research_pm_sufficiency = bool(re.search(
        r"(?:experiencia|experiencia previa|experiencia profesional|experi[eè]ncia).{0,180}"
        r"(?:departamento|area|unidad).{0,100}(?:gestion|gestio).{0,100}(?:proyectos?|projectes?).{0,80}(?:i\+d\+i|investigacion|recerca)?"
        r".{0,260}criterio de suficiencia.{0,120}(?:minimo|minim|minimum).{0,40}(?:\d+\s*(?:puntos?|ptos|punts))",
        t, re.I
    ))
    if research_pm_sufficiency:
        gaps.append("research_project_management_sufficiency_experience")

    return sorted(set(gaps))


def _mandatory_qualification_gaps(text: str) -> list[str]:
    """Detect narrowly defined mandatory credentials not evidenced in the profile.

    This is intentionally not a generic degree-level checker: a higher academic degree can
    often satisfy broad education requirements. We only flag recruitment language that
    requires a specific vocational technician credential (e.g. FP/CFGS/Técnico Superior)
    inside the necessary/indispensable requirements section. Such credentials are distinct
    professional qualifications and are not evidenced by the profile's BSc/MSc/PhD.
    """
    t = normalize(text)
    gaps: list[str] = []

    # Restrict matching to the actual mandatory-requirements section so an FP/CFGS item
    # appearing later under "Méritos valorables" does not become a false eligibility gap.
    section_match = re.search(
        r"(?:requisitos? necesarios?|requisitos? indispensables?|requisits? necessaris?|requisits? indispensables?|required qualifications?|essential qualifications?)"
        r"(?P<section>.{0,1200}?)(?=(?:valoracion de meritos|valoracio de merits|meritos valorables|merits valorables|preferred qualifications|desirable|funciones|functions|$))",
        t, re.I
    )
    required_section = section_match.group("section") if section_match else ""
    vocational_credential = bool(re.search(
        r"(?:formacion profesional|formacio professional).{0,80}(?:grado superior|grau superior)"
        r"|(?:ciclo formativo|cicle formatiu).{0,80}(?:grado superior|grau superior)"
        r"|\bcfgs\b"
        r"|(?:titulo|titulacion|titulacio).{0,100}(?:tecnico superior|tecnic superior)"
        r"|(?:meces\s*1|eqf\s*5).{0,120}(?:formacion profesional|formacio professional|tecnico superior|tecnic superior)"
        r"|(?:formacion profesional|formacio professional|tecnico superior|tecnic superior).{0,120}(?:meces\s*1|eqf\s*5)",
        required_section, re.I
    ))
    if vocational_credential:
        gaps.append("mandatory_specific_vocational_qualification")

    return gaps


def hard_blockers(text: str, title: str) -> list[str]:
    norm_title = normalize(title)
    combined = f"{norm_title}\n{normalize(text)}"
    blockers = []
    for name, patterns in HARD_BLOCKERS.items():
        if any(re.search(p, combined, re.I) for p in patterns):
            blockers.append(name)

    # Internship is title-level only. A footer or related-jobs link saying "internship"
    # must never zero-score a postdoc or researcher vacancy.
    if re.search(r"\b(?:internship|intern|practicas|practiques)\b", norm_title, re.I):
        blockers.append("internship")

    # Doctoral-training / predoctoral vacancies are outside the target because the user
    # already holds a PhD. Keep this title-level so "doctoral" inside a postdoc JD does
    # not create false blockers.
    if re.search(
        r"\bpre[- ]?doctoral\b|\bpredoctoral\b|\bphd (?:student|position|candidate|fellowship|researcher)\b|"
        r"\bdoctoral (?:candidate|student|fellow|network)\b|\bresearch staff in training\b|\bdoctorand",
        norm_title, re.I
    ):
        blockers.append("doctoral_training_position")

    # Some EURAXESS titles are generic (e.g. "Researcher") even though the full JD
    # explicitly defines a PhD/doctoral-training vacancy. Re-run a narrow eligibility gate
    # on the full description so already-PhD candidates are not scored as normal jobs.
    if re.search(
        r"candidates? must not (?:already )?(?:possess|hold|have) (?:a )?doctoral degree|"
        r"must not (?:already )?(?:possess|hold|have) (?:a )?phd|"
        r"current(?:ly)? enrol(?:l)?(?:ed|ment).{0,80}(?:phd|doctoral) programme|"
        r"fully funded phd position|offers? \d+ fully funded phd position|"
        r"successful candidates? will obtain (?:a )?(?:joint |double )?doctoral degree|"
        r"meet admission requirements? for (?:the )?phd program",
        normalize(text), re.I
    ):
        blockers.append("doctoral_training_position_jd")

    # Distinguish host-search / expression-of-interest notices for future fellowships from
    # actual funded job vacancies. Real COFUND programmes offering employment are not caught.
    fellowship_hosting = bool(
        re.search(r"(?:expression of interest|interested in applying|co[- ]develop).{0,160}(?:msca|marie sklodowska|postdoctoral fellowship)", normalize(text), re.I)
        or re.search(r"(?:msca|marie sklodowska|postdoctoral fellowship).{0,160}(?:co[- ]write|co[- ]develop|support for the application|host institution)", normalize(text), re.I)
        or re.search(
            r"(?:seeking|looking for|call for applications?).{0,160}(?:postdoctoral )?candidate.{0,180}(?:eligible to apply|apply for).{0,120}(?:fellowship|fellow|grant)",
            normalize(text), re.I
        )
        or re.search(
            r"(?:candidate|candidato|candidata).{0,160}(?:eligible|elegible).{0,100}(?:apply|solicitar|presentar).{0,120}(?:fellowship|beca|ayuda)",
            normalize(text), re.I
        )
    )
    if fellowship_hosting and not re.search(r"(?:offers?|offering) \d+ positions|employment contract|will be hired", normalize(text), re.I):
        blockers.append("fellowship_hosting_call")

    if re.search(r"project manager|project coordinator|project officer", norm_title):
        distant = _matches(combined, DISTANT_DOMAINS)
        core = _matches(combined, CORE_DOMAINS)
        adjacent = _matches(combined, ADJACENT_DOMAINS)
        if distant and not core and not adjacent:
            blockers.append("project_management_in_distant_domain")

    if re.search(r"(?:must|required).{0,50}(?:work authorization|right to work).{0,50}(?:united states|usa|uk|united kingdom|germany|france)", combined, re.I):
        blockers.append("work_authorization_outside_spain")
    return sorted(set(blockers))


def evaluate_job(job: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(job.get("title"))
    jd = clean_text(job.get("full_detail") or job.get("description"))
    text = f"{title}\n{jd}"
    norm = normalize(text)

    blockers = hard_blockers(jd, title)
    domain_category, domain_hits, distant_hits = detect_domain(norm)
    family, _ = detect_family(title)

    # Slash-gendered Spanish/Catalan titles normalize to forms such as
    # "investigador a clinico a". Prefer the clinical-research family over the generic
    # "investigador" academic match when the title explicitly says clinical researcher.
    if re.search(r"\binvestigador(?: a)? clinico(?: a)?\b|\binvestigadora clinica\b", normalize(title), re.I):
        family = "clinical_human_research"

    # Generic Project Manager/Coordinator/Officer titles become a research-project
    # family only when the full JD demonstrates a relevant scientific/health domain
    # and genuine research-project context. This lets a role such as an exercise/
    # physical-activity Horizon Europe project manager score correctly without letting
    # generic SAP/energy/business project management into the target family.
    if family == "unclear" and re.search(r"\bproject (?:manager|coordinator|officer)\b", normalize(title), re.I):
        research_context = bool(re.search(
            r"\bresearch\b|\bscientific\b|\bclinical\b|\bhorizon europe\b|\binternational consortium\b|\beu project",
            norm, re.I
        ))
        if domain_category in {"CORE", "ADJACENT"} and research_context:
            family = "research_project_management"

    # A research-project-management role embedded explicitly in biomedical/health
    # research is adjacent even when the project topic itself is broad or unspecified.
    # Restrict this promotion to the PM family so generic biomedical wet-lab roles do
    # not receive a domain boost from institutional context alone.
    if family == "research_project_management" and domain_category == "UNCLEAR" and re.search(
        r"biomedical research|health research|clinical research institute|hospital research|research institute.{0,100}(?:health|biomedical)",
        norm, re.I
    ):
        domain_category = "ADJACENT"
        domain_hits = sorted(set(domain_hits + ["health_sciences"]))

    # Some public-sector/research-centre adverts use descriptive or grade-based titles
    # rather than a canonical role name. Infer a family from the full JD only when several
    # role-defining signals co-occur; this is deliberately stricter than title matching.
    if family == "unclear" and domain_category in {"CORE", "ADJACENT"}:
        eu_pm_signals = [
            bool(re.search(r"(?:project )?(?:management|coordination|monitoring).{0,100}(?:project|activities|study)|support.{0,60}(?:management|coordination)", norm, re.I)),
            bool(re.search(r"deliverables?|milestones?|work packages?|action points?", norm, re.I)),
            bool(re.search(r"horizon europe|european commission|eu[- ]funded|european (?:r&i|research|project)|consortium partners?", norm, re.I)),
            bool(re.search(r"consortium meetings?|project meetings?|reporting.{0,80}(?:commission|funder|consortium)", norm, re.I)),
        ]
        if sum(eu_pm_signals) >= 3:
            family = "research_project_management"

    if family == "unclear" and domain_category in {"CORE", "ADJACENT"}:
        clinical_coord_signals = [
            bool(re.search(r"coordination.{0,80}(?:clinical trial|clinical study|research stud)|support.{0,80}coordination.{0,80}(?:trial|study)", norm, re.I)),
            bool(re.search(r"participant|patient.{0,40}(?:recruit|follow[- ]?up|visit)|recruitment.{0,80}(?:patient|participant)", norm, re.I)),
            bool(re.search(r"\becrf\b|\bredcap\b|clinical data capture|case report form", norm, re.I)),
            bool(re.search(r"study documentation|trial documentation|monitoring visit|good clinical practice|\bgcp\b|ethics committee", norm, re.I)),
        ]
        if sum(clinical_coord_signals) >= 2:
            family = "clinical_human_research"

    # A nominal research-management title can actually be a specialist science-communication
    # position. Detect this semantically rather than only for the English title "Research
    # Manager": Spanish/Catalan public-research employers often use generic grades such as
    # "Técnico/a de gestión de la investigación" while the actual area and duties are
    # communication, dissemination, media, events or journalism. Require multiple specialist
    # communication signals so genuine research-project managers who merely disseminate
    # project results are not demoted.
    communication_title_or_area = bool(re.search(
        r"communication|comunicacion|comunicacio|difusion de la ciencia|difusio de la ciencia|divulgacion cientifica|divulgacio cientifica",
        normalize(title), re.I
    ))
    communication_duties = [
        bool(re.search(r"science communication|comunicacion cientifica|comunicacio cientifica|divulgacion cientifica|divulgacio cientifica", norm, re.I)),
        bool(re.search(r"media relations?|relaciones con los medios|relacions amb els mitjans|press office|gabinete de prensa|gabinet de premsa", norm, re.I)),
        bool(re.search(r"social media|redes sociales|xarxes socials|digital channels?|canales digitales|canals digitals", norm, re.I)),
        bool(re.search(r"journalism|periodismo|periodisme|audiovisual communication|comunicacion audiovisual|comunicacio audiovisual|advertising and public relations|publicidad y relaciones publicas|publicitat i relacions publiques", norm, re.I)),
        bool(re.search(r"communication events?|communication campaigns?|eventos? divulgativos?|esdeveniments? divulgatius?|communication strategy|estrategia de comunicacion|estrategia de comunicacio", norm, re.I)),
    ]
    communication_specialist_role = bool(
        family == "research_project_management"
        and communication_title_or_area
        and sum(communication_duties) >= 2
    ) or bool(
        re.search(r"\bresearch manager\b", normalize(title), re.I)
        and re.search(r"\bcommunication sciences?\b|\bscience communication\b|\binstitutional communication\b|\bcorporate communication\b", norm, re.I)
        and re.search(r"advertising and public relations|audiovisual communication|journalism|communication", norm, re.I)
    )
    if communication_specialist_role:
        family = "unclear"

    # Narrow title-level mismatches override incidental health/science terms from page
    # chrome, employer descriptions or unrelated programme lists.
    title_norm = normalize(title)
    title_distant_hits = _matches(title_norm, TITLE_DISTANT_PATTERNS)
    title_core_hits = _matches(title_norm, CORE_DOMAINS)
    title_adjacent_hits = _matches(title_norm, ADJACENT_DOMAINS)
    if (
        title_distant_hits and not title_core_hits and not title_adjacent_hits
        and family not in {"research_project_management", "clinical_human_research", "scientific_health_innovation"}
    ):
        domain_category = "DISTANT"
        domain_hits = []
        distant_hits = sorted(set(distant_hits + title_distant_hits))

    # "IT Project Manager" is not generic research-project management merely because it
    # sits inside a research institute. The title itself defines an IT/ICT operational
    # profession. Keep this narrow so ordinary Horizon/health research PM titles are
    # unaffected.
    explicit_it_pm_title = bool(re.search(
        r"\b(?:it|ict) project manager\b|\bproject manager.{0,25}(?:it|ict|cloud infrastructure|information technology)\b",
        title_norm, re.I
    ))
    if explicit_it_pm_title and not title_core_hits and not title_adjacent_hits:
        domain_category = "DISTANT"
        domain_hits = []
        distant_hits = sorted(set(distant_hits + ["software_it"]))

    fit, partial, missing = [], [], []

    if blockers:
        return Evaluation(
            score=0,
            recommendation="SKIP",
            domain_category=domain_category,
            job_family=family,
            fit_signals=domain_hits,
            partial_matches=[],
            missing_requirements=[],
            blockers=blockers,
            reason="Hard blocker detected before scoring."
        ).to_dict()

    # Domain: 0-30
    if domain_category == "CORE":
        domain_score = 30
        fit.append("Core scientific domain: " + ", ".join(domain_hits[:4]))
    elif domain_category == "ADJACENT":
        domain_score = 20
        fit.append("Adjacent health/research domain: " + ", ".join(domain_hits[:4]))
    elif domain_category == "UNCLEAR":
        domain_score = 8
        partial.append("Scientific domain unclear")
    else:
        domain_score = 0
        partial.append("Distant domain: " + ", ".join(distant_hits[:3]))

    family_scores = {
        "research_academic": 25,
        "research_project_management": 24,
        "clinical_human_research": 24,
        "scientific_health_innovation": 18,
        "unclear": 5,
    }
    family_score = family_scores[family]
    if family != "unclear":
        fit.append("Target job family: " + family)
    else:
        partial.append("Job family not clearly targeted")

    exp_hits = _matches(norm, DIRECT_EXPERIENCE_SIGNALS)
    exp_score = min(20, len(exp_hits) * 4)
    if exp_hits:
        fit.append("CV-aligned responsibilities: " + ", ".join(exp_hits[:5]))
    else:
        partial.append("Few explicit transferable-experience signals in JD")

    method_hits = _matches(norm, METHOD_SIGNALS)
    method_score = min(10, len(method_hits) * 3)
    if method_hits:
        fit.append("Methods overlap: " + ", ".join(method_hits[:4]))

    specialist_gap_hits = _matches(norm, SPECIALIST_ACADEMIC_GAPS)
    if specialist_gap_hits:
        missing.append("Specialist academic/domain requirement not directly evidenced in CV: " + ", ".join(specialist_gap_hits))

    specialist_method_gaps = _specialist_method_gaps(norm)
    if specialist_method_gaps:
        missing.append("Specialist methods/background not evidenced in CV: " + ", ".join(specialist_method_gaps))

    mandatory_experience_gaps = _mandatory_experience_gaps(norm)
    if mandatory_experience_gaps:
        missing.append("Mandatory specialist prior experience not evidenced in CV: " + ", ".join(mandatory_experience_gaps))

    mandatory_qualification_gaps = _mandatory_qualification_gaps(norm)
    if mandatory_qualification_gaps:
        missing.append("Mandatory specific qualification not evidenced in CV: " + ", ".join(mandatory_qualification_gaps))

    qual_score = 7
    if re.search(r"\bphd\b|doctorate|doctoral degree", norm):
        qual_score = 10
        fit.append("PhD-level qualification aligned")
    if re.search(r"\b(master|msc)\b", norm) and not re.search(r"\bphd\b|doctorate", norm):
        qual_score = 8
    senior_match = re.search(r"(?:minimum|at least|al menos)\s*(\d+)\+?\s*years?", norm)
    if senior_match and int(senior_match.group(1)) >= 8:
        qual_score = min(qual_score, 3)
        partial.append("Very senior experience requirement")
    elif senior_match and int(senior_match.group(1)) >= 5:
        qual_score = min(qual_score, 6)
        partial.append("High experience requirement")

    loc_score, loc_fit, loc_partial = location_points(job, jd)
    fit.extend(loc_fit)
    partial.extend(loc_partial)
    if re.search(r"spanish.{0,30}(?:b2|c1|fluent|required)|(?:b2|c1|fluent|required).{0,30}spanish", norm):
        partial.append("Spanish requirement above documented B1; review but do not auto-skip")
        loc_score = max(1, loc_score - 1)

    catalan_high_required = bool(re.search(
        r"(?:catalan|catala).{0,40}(?:fluent|high level|nivell alt|nivell fluid|nivell fluit|fluid|fluit)|(?:fluent|high level|nivell alt|nivell fluid|nivell fluit|fluid|fluit).{0,40}(?:catalan|catala)",
        norm, re.I
    ))
    if catalan_high_required:
        missing.append("High/fluent Catalan requested; not documented in CV")

    score = int(round(domain_score + family_score + exp_score + method_score + qual_score + loc_score))

    # Precision guardrails.
    if domain_category == "DISTANT":
        score = min(score, 49)
    if domain_category == "ADJACENT" and family == "unclear":
        score = min(score, 74)
    if family == "research_project_management" and domain_category == "UNCLEAR":
        score = min(score, 64)
    # Precision-first rule: a generic researcher/postdoc is not a primary candidate
    # unless the scientific domain itself is relevant. Transferable skills alone are
    # insufficient to put an unrelated academic role into REVIEW/APPLY.
    if family == "research_academic" and domain_category == "UNCLEAR":
        score = min(score, 59)
    if family in {"clinical_human_research", "scientific_health_innovation"} and domain_category == "UNCLEAR":
        score = min(score, 64)

    # A required specialist academic field/track record is a major fit gap, not a minor
    # postdoc penalty. Keep such roles out of the primary shortlist in precision-first mode.
    if specialist_gap_hits and family == "research_academic":
        score = min(score, 59)

    # Multiple specialist lab requirements that are absent from the CV make the role a poor
    # practical match even when generic health/research words are present.
    if specialist_method_gaps and domain_category != "CORE":
        score = min(score, 49)
    if "patch_clamp_electrophysiology" in specialist_method_gaps:
        score = min(score, 49)

    # Explicit minimum prior experience in regulated trial operations is a practical
    # eligibility gap when the CV shows academic intervention/RCT work but no sponsor/CRO
    # clinical-trial operations background. Keep such roles out of the apply/review queue.
    if "regulated_clinical_trial_operations_experience" in mandatory_experience_gaps:
        score = min(score, 49)
    if "hospital_clinical_data_operations_experience" in mandatory_experience_gaps:
        score = min(score, 49)
    if "research_grant_financial_management_experience" in mandatory_experience_gaps:
        score = min(score, 49)
    if "preaward_grant_operations_experience" in mandatory_experience_gaps:
        score = min(score, 49)
    if "research_project_management_sufficiency_experience" in mandatory_experience_gaps:
        score = min(score, 49)
    if "mandatory_specific_vocational_qualification" in mandatory_qualification_gaps:
        score = min(score, 49)

    if catalan_high_required:
        score = min(score, 64)

    if communication_specialist_role:
        missing.append("Role is primarily specialist research/science communication rather than research project management")
        score = min(score, 49)

    if score >= 90:
        rec = "STRONG_APPLY"
    elif score >= 80:
        rec = "APPLY"
    elif score >= 65:
        rec = "REVIEW"
    elif score >= 50:
        rec = "LOW_PRIORITY"
    else:
        rec = "SKIP"

    reason = f"{domain_category} domain + {family} family; component score {score}/100."
    return Evaluation(score, rec, domain_category, family, fit, partial, missing, [], reason).to_dict()
