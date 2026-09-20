import re

CORE_DOMAINS = {
    "exercise_physiology": [r"exercise physiology", r"fisiologia del ejercicio", r"fisiologia de l exercici"],
    "exercise_science": [r"exercise science", r"ciencias? del ejercicio"],
    "sport_exercise_science": [r"sport and exercise science", r"sport science", r"sports science", r"ciencias? del deporte", r"ciencies? de l esport"],
    "physical_activity": [r"physical activity", r"actividad fisica", r"activitat fisica"],
    "exercise_intervention": [r"exercise intervention", r"exercise training", r"intervencion.*ejercicio"],
    "exercise_neuroscience": [r"exercise neuroscience", r"exercise.{0,80}brain", r"physical activity.{0,80}brain"],
    "health_fitness": [r"\bhealth related fitness\b", r"\bphysical fitness\b", r"\bcardiorespiratory fitness\b", r"\bfitness (?:assessment|testing)\b"],
    "exercise_cognition": [r"exercise.*cognition", r"physical activity.*cognition"],
    "physical_function": [
        r"\bphysical function\b",
        r"\bfunctional capacity\b.{0,80}\b(?:physical|exercise|mobility|fitness|older adults?|patients?|participants?)\b",
        r"\b(?:physical|exercise|mobility|fitness|older adults?|patients?|participants?)\b.{0,80}\bfunctional capacity\b",
    ]
}

ADJACENT_DOMAINS = {
    "healthy_ageing": [r"\bhealthy ageing\b", r"\bhealthy aging\b", r"\bageing\b", r"\baging\b"],
    "sarcopenia": [r"sarcopenia"],
    "rehabilitation": [r"rehabilitation", r"rehabilitacion", r"rehabilitacio"],
    "neurology": [r"\bneurology\b", r"\bneurological\b", r"\bneuroscience\b", r"\bbrain health\b"],
    "cognitive_health": [r"\bcognitive health\b", r"\bcognition\b", r"\bcognitive (?:function|performance|development|science|neuroscience)\b"],
    "mental_health": [
        r"\bmental health\b", r"\bmental wellbeing\b", r"\bpsychological wellbeing\b",
        r"\bsalud mental\b", r"\bsalut mental\b",
        r"\bpsychiatr(?:y|ic)\b", r"\bpsychotic disorders?\b", r"\baffective disorders?\b",
        r"\bclinical psychology\b", r"\bhealth psychology\b", r"\bchild and adolescent psychiatry\b",
    ],
    "stress": [r"\bpsychological stress\b", r"\bpsychosocial stress\b", r"\bstress[- ]related\b", r"\bpsychobiolog", r"\bcortisol\b"],
    "behavioural_medicine": [r"behavio.?ral medicine", r"behavio.?ral health"],
    "lifestyle": [r"\blifestyle medicine\b", r"\blifestyle intervention\b", r"\blifestyle behavio.?rs?\b", r"\bhealthy lifestyle\b"],
    "preventive_health": [r"\bpreventive health\b", r"\bhealth promotion\b", r"\bpublic health\b", r"\benvironmental health\b", r"\burban health\b", r"\bepidemiolog", r"\bsalud publica\b", r"\bsalut publica\b"],
    "digital_health": [r"\bdigital health\b", r"\bsalud digital\b", r"\bsalut digital\b", r"\behealth\b", r"\bmhealth\b", r"\bvirtual reality\b.{0,80}\bhealth", r"\bvr\b.{0,80}\bhealth"],
    "behaviour_change": [r"behavio.?r change", r"cambio de comportamiento", r"canvi de comportament"],
    "obesity": [r"obesity", r"obesidad", r"obesitat"],
    "disability": [r"\bintellectual and developmental disabilities\b", r"\bdevelopmental disabilities\b", r"\bdisability research\b", r"\bdisability health\b", r"\b(?:people|adults|children|participants|patients) with disabilit(?:y|ies)\b"],
    "human_performance": [r"human performance"],
    "clinical_exercise": [r"clinical exercise"],
    "health_sciences": [r"\bhealth sciences?\b", r"\bciencias? de la salud\b", r"\bciencies? de la salut\b"],
    "health_innovation": [r"\bhealth innovation\b", r"\binnovacion en salud\b", r"\binnovacio en salut\b", r"\binnovacio.{0,40}ciencies? de la vida\b"]
}

DISTANT_DOMAINS = {
    "software_it": [
        r"software development", r"software engineer", r"devops", r"cybersecurity", r"telecommunications",
        r"communications? networks?", r"redes? de comunicaciones?", r"sistemas? de comunicaciones?",
        r"cloud[- ]native infrastructure", r"containeri[sz]ed infrastructure", r"\bkubernetes\b",
    ],
    "finance": [r"banking", r"finance", r"financial services"],
    "energy": [r"renewable energy", r"energy sector", r"\bsolar\b", r"wind energy", r"nuclear energy", r"nuclear reactor", r"small modular reactor", r"offshore energy hub"],
    "construction_industrial": [r"construction", r"industrial engineering", r"materials science", r"thermoelectric", r"device fabrication"],
    "agriculture_environment": [r"agricultural sciences?", r"\bagrifood\b", r"agroecolog", r"soil science", r"crop productivity", r"horticultur", r"forest science", r"chemical looping", r"thermochemical", r"pyrolysis", r"gasification", r"biorefinery"],
    "computational_specialist": [r"computer vision", r"deep learning", r"foundation models?", r"spatial transcriptomics", r"bioinformatics", r"multiomics", r"proteomics"],
    "pharma_specialist": [r"drug discovery", r"pharmaceutical formulation", r"molecular diagnostics", r"phase i oncology"],
    "data_engineering": [r"data engineer", r"data engineering"],
    "generic_business": [r"sap migration", r"erp implementation", r"supply chain", r"marketing operations"]
}

JOB_FAMILIES = {
    "research_academic": [
        r"postdoctoral researcher", r"postdoctoral fellow", r"postdoctoral scientist", r"postdoc",
        r"research scientist", r"research fellow", r"health researcher", r"exercise researcher",
        r"exercise scientist", r"exercise physiologist", r"physical activity researcher",
        r"sport science researcher", r"investigador", r"investigadora"
    ],
    "research_project_management": [
        r"research project manager", r"scientific project manager", r"research project coordinator",
        r"scientific project coordinator", r"research manager", r"research officer", r"research project officer",
        r"scientific project officer", r"eu project manager", r"european project manager", r"european projects manager",
        r"european project coordinator", r"european projects coordinator",
        r"european projects officer", r"eu projects officer", r"horizon europe project manager",
        r"research grants officer", r"grants manager", r"health research project manager",
        r"pre award (?:grants? )?officer", r"post award (?:grants? )?officer",
        r"international projects officer", r"european (?:and )?international projects officer",
        r"r&d&i officer", r"r\s*&\s*d\s*&\s*i officer", r"research and innovation officer",
        r"research innovation officer", r"knowledge transfer officer", r"technology transfer officer",
        r"gestor.? de proyectos de investigacion", r"coordinador.? de proyectos de investigacion",
        r"tecnic(?:o(?: a)?|a) de gestion de la investigacion",
        r"tecnic(?:o(?: a)?|a) de gestion de investigacion",
        r"tecnic(?:o(?: a)?|a) de gestion de proyectos de investigacion",
        r"tecnic(?: a)? de gestio de la recerca", r"tecnic(?: a)? de gestio de projectes de recerca",
        r"gestor.? de proyectos europeos", r"tecnico.? de proyectos europeos",
        r"coordinador.? de proyectos europeos", r"gestor.? de investigacion",
        r"tecnico.? de investigacion", r"gestor.? de subvenciones", r"gestor.? de proyectos cientificos",
        r"gestor.? de projectes de recerca", r"coordinador.? de projectes de recerca",
        r"gestor.? de projectes europeus", r"tecnic.? de projectes europeus",
        r"coordinador.? de projectes europeus", r"tecnic(?: a)? de projectes d innovacio",
        r"tecnic(?: a)? de projectes de innovacio"
    ],
    "research_data": [
        r"research data manager", r"scientific data manager",
        r"research data analyst", r"scientific data analyst",
        r"research data officer", r"scientific data officer",
        r"health data analyst", r"clinical data manager",
        r"data manager and data analyst", r"research data coordinator",
        r"scientific data coordinator"
    ],
    "clinical_human_research": [
        r"clinical research coordinator", r"study coordinator", r"trial coordinator", r"clinical trial coordinator", r"clinical trials coordinator", r"clinical study coordinator",
        r"clinical project coordinator", r"research study coordinator", r"clinical researcher",
        r"investigador.? clinico", r"investigadora.? clinica", r"investigador.?a clinico.?a",
        r"coordinador.? de investigacion clinica", r"coordinador.? de ensayos clinicos",
        r"coordinador.? de estudios clinicos", r"tecnico.? de investigacion clinica",
        r"clinical operations", r"clinical research operations"
    ],
    "scientific_health_innovation": [
        r"scientific affairs specialist", r"medical writer", r"scientific writer",
        r"health innovation project manager", r"digital health researcher",
        r"scientific coordinator", r"research programme officer", r"research program officer",
        r"methodological support", r"methodology support", r"epidemiology and biostatistics",
        r"promotor(?: a)?.{0,80}innovacio.{0,40}salut", r"promotor(?: a)? d innovacio", r"promotor(?: a)? de innovacio", r"tecnic(?: a)? d innovacio en salut",
        r"tecnic(?: a)? de innovacion en salud"
    ]
}

DIRECT_EXPERIENCE_SIGNALS = {
    "rct": [r"randomi[sz]ed controlled trial", r"randomi[sz]ed.{0,30}intervention", r"\brct\b", r"ensayo controlado aleator"],
    "human_intervention": [r"human intervention", r"intervention stud", r"intervention trial"],
    "project_coordination": [r"project coordination", r"project coordinator", r"coordinat.*project", r"consortium coordination", r"coordinacion.{0,40}proyectos?", r"gestion.{0,40}proyectos?", r"coordinacio.{0,40}projectes?", r"gestio.{0,40}projectes?"],
    "eu_projects": [r"horizon europe", r"marie sklodowska", r"\bmsca\b", r"eu funded", r"european commission", r"european research project", r"proyectos? europeos?", r"projectes? europeus?", r"consorcios? europeos?", r"consorcis? europeus?"],
    "grants": [r"grant writing", r"grant management", r"grant reporting", r"research grants?", r"proposal development", r"propuestas? de financiacion", r"propostes? de financament", r"gestion.{0,30}subvenciones?", r"gestio.{0,30}subvencions?"],
    "international": [r"international consortium", r"international collaboration", r"international.{0,40}projects?", r"multidisciplinary", r"consorcio internacional", r"consorci internacional", r"colaboracion internacional", r"collaboracio internacional", r"agents?.{0,40}internacionals?"],
    "scientific_writing": [r"scientific writing", r"manuscript", r"publication", r"redaccion cientifica", r"escriptura cientifica", r"publicaciones? cientificas?", r"publicacions? cientifiques?"],
    "data_stats": [r"statistical analysis", r"\bspss\b", r"\busing r\b", r"\br (?:software|programming|language|package)\b", r"data analysis", r"analisis estadistico", r"analisi estadistica", r"analisis de datos", r"analisi de dades"],
    "assessment": [r"physiological assessment", r"fitness assessment", r"cognitive assessment", r"psychological assessment", r"evaluacion fisiologica", r"valoracion fisiologica", r"evaluacion de la condicion fisica", r"evaluacion cognitiva", r"evaluacion psicologica"]
}

METHOD_SIGNALS = {
    "exercise_testing": [r"vo2", r"cardiopulmonary exercise test", r"cpet", r"fitness testing"],
    "physiology": [r"physiological", r"cortisol", r"heart rate", r"hrv"],
    "questionnaires": [r"questionnaire", r"psychological assessment", r"lifestyle assessment"],
    "statistics": [r"\bspss\b", r"\busing r\b", r"\br (?:software|programming|language|package)\b", r"statistical analysis"]
}

HARD_BLOCKERS = {
    "mandatory_md": [
        r"(?:md|medical degree|degree in medicine).{0,50}(?:required|mandatory|essential|imprescindible)",
        r"(?:required|mandatory|essential|imprescindible).{0,50}(?:md|medical degree|degree in medicine)",
        r"education and qualifications.{0,120}required.{0,40}degree in medicine",
        r"(?:titulacion requerida|titulacio requerida).{0,120}(?:grado|grau|licenciatura).{0,80}(?:en )?medicina",
        r"(?:requisitos? necesarios?|requisits? necessaris?).{0,260}(?:grado|grau|licenciatura).{0,80}(?:en )?medicina",
        r"required.{0,80}specialist medical training",
    ],
    "mandatory_nursing": [
        r"nursing degree.{0,40}(?:required|mandatory|essential|imprescindible)",
        r"(?:required|mandatory|essential|imprescindible).{0,60}(?:nursing degree|degree in nursing)",
        r"requisitos? necesarios?.{0,260}titulacion.{0,160}(?:en )?enfermeria",
        r"requisits? necessaris?.{0,260}titulacio.{0,160}(?:en )?infermeria",
    ],
    "mandatory_pharmacy": [r"pharmacy degree.{0,40}(?:required|mandatory|essential|imprescindible)"],
    "cra_monitoring": [r"(?:minimum|at least|al menos)\s*[3-9]\+?\s*years?.{0,80}(?:cra|clinical monitoring|site monitoring)"],
    "pharma_industry": [r"(?:minimum|at least|al menos)\s*[3-9]\+?\s*years?.{0,80}(?:pharmaceutical industry|pharma industry)"],
    "specialist_wet_lab": [r"(?:mandatory|required|essential).{0,50}(?:flow cytometry|mass spectrometry|crispr|cell culture)"],
    "catalan_c2": [r"(?:native|bilingual|c2).{0,30}(?:catalan|catala)", r"(?:catalan|catala).{0,35}(?:mandatory|required|imprescindible)"],
    "regulated_clinical_profession": [
        r"(?:perfil que buscamos|perfil que busquem|required qualifications?|requirements?).{0,220}(?:grado|licenciatura|degree).{0,80}medicina.{0,180}psicolog.{0,180}enfermer",
        r"(?:medicina|medicine).{0,80}(?:mir|speciali[sz]ation).{0,180}psicolog.{0,120}(?:habilitacion sanitaria|health licen[cs]e).{0,180}enfermer",
    ],
}

PREFERRED_MARKERS = [r"preferred", r"desirable", r"nice to have", r"plus", r"valorable", r"deseable"]
REQUIRED_MARKERS = [r"required", r"mandatory", r"essential", r"must have", r"imprescindible", r"requisito"]


SPECIALIST_ACADEMIC_GAPS = {
    "epidemiology_environmental_health": [
        r"phd.{0,100}(?:epidemiology|environmental health|biostatistics)",
        r"(?:demonstrated|strong|proven).{0,80}(?:record|experience).{0,80}(?:epidemiology|environmental health)",
        r"experience.{0,80}health impact assessment",
    ],
    "clinical_psychology_specialism": [
        r"phd.{0,100}(?:clinical psychology|clinical neuropsychology)",
    ],
    "biostatistics_specialism": [
        r"(?:head|lead|senior).{0,50}biostatistics",
        r"(?:degree|phd|master).{0,80}(?:biostatistics|statistics).{0,80}(?:required|essential|mandatory)",
    ],
}

# Strong title-level domain mismatches. These override noisy generic health words that may
# appear elsewhere on a portal page. They are intentionally narrow.
TITLE_DISTANT_PATTERNS = {
    "computational_language_ai": [r"computational linguistics", r"\bnlp\b", r"natural language processing"],
    "earth_environmental_data": [r"\bearth data\b", r"air quality monitoring", r"soil ecology"],
    "unrelated_molecular_biology": [r"rna decay", r"protein synthesis", r"protein engineering", r"molecular oncology", r"cell signaling", r"protein synthesis"],
    "medical_imaging_engineering": [r"medical imaging simulation", r"ai[- ]based quantitative medical imaging", r"research engineer.*medical imaging"],
    "oncology_cancer_specialist": [r"\bcancer\b", r"\boncology\b", r"pancreas regeneration", r"tumou?r"],
    "materials_membranes": [r"ion[- ]exchange membranes?", r"electrodialysis", r"materials science"],
    "bioinformatics_computing": [r"bioinformatician", r"computer scientist", r"machine learning.*industrial", r"quantum device"],
    "it_telecom_operations": [
        r"\bit project manager\b", r"\bict project manager\b",
        r"researcher.{0,40}(?:communications? networks?|redes? de comunicaciones?|telecommunications?)",
        r"investigador.{0,50}(?:redes? de comunicaciones?|sistemas? de comunicaciones?|telecomunicaciones?)",
    ],
    "procurement_legal_admin": [r"public procurement officer", r"procurement officer", r"contracting officer"],
    "construction_energy": [r"sustainable construction", r"building energy efficiency", r"smart buildings", r"small modular reactors?", r"nuclear reactors?", r"offshore energy hubs?"],
    "unrelated_environment_agriculture": [
        r"agricultural ecosystems?", r"game species conservation", r"carbonate geochemistry", r"critical raw materials",
        r"water treatment", r"wastewater treatment", r"tratamiento de aguas residuales", r"tratament d aigues residuals",
        r"tecnologia de membranas", r"tecnologia de membranes", r"ecological succession", r"prebiotic chemistry", r"origin of life"
    ],
}
