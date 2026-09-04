# -*- coding: utf-8 -*-
"""Gen5 ReCo Platform Adapters for Bosch RCC1010 CornerBase."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, List, Tuple

from .base import (
    BaseCodeLearnerAdapter,
    BaseConditionExtractorAdapter,
    BaseSignalMapperAdapter,
)
from .factory import (
    register_code_learner,
    register_condition_extractor,
    register_signal_mapper,
)


@register_code_learner("gen5_reco_pl")
class Gen5RecoCodeLearnerAdapter(BaseCodeLearnerAdapter):
    """Code learner adapter for Gen5 ReCo (Bosch RCC1010) C++ codebase."""

    KEY_SOURCE_FILES: list[str] = [
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_bsdStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_lcaStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_rctaStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_fctaStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_dowStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssStateMachine.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssActiveState.cpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssPassiveState.cpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssFcp.hpp",
        "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssState.hpp",
        "reco_fw/component/fct/modules/runCont/decisionMaker/decisionMakerController.hpp",
        "reco_fw/component/fct/modules/behaviorManager/fct_s_behaviorManager.cpp",
        "reco_fw/component/fct/modules/behaviorManager/fct_s_behaviorManager.hpp",
        "reco_fw/component/fct/modules/fct_s_hmiSpecification.hpp",
        "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.cpp",
        "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.hpp",
        "reco_fw/component/sit/modules/behaviorStrategies/TIPL/laneChangeWarningTIPL/",
        "reco_fw/component/sit/modules/behaviorStrategies/FM/",
        "reco_fw/component/per/runnables/per_sppRLocRunnable.cpp",
        "reco_fw/component/per/runnables/per_sppBdmRunnable.cpp",
        "reco_fw/component/per/runnables/per_sppStalinRunnable.cpp",
        "apl/base/component/fct/config/padfct/padfct_s_par_gen.h",
        "apl/base/component/fct/config/padfct/padfct_s_rctb.h",
        "apl/base/component/fct/config/padfct/padfct_s_fcta.h",
        "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_bsdlca.hpp",
        "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_fcta.hpp",
        "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_rcta.hpp",
        "reco_fw/component/per/parameters/per_bdmParameters.hpp",
        "reco_fw/component/per/interfaces/per_fusedObjectsDynamic.hpp",
        "reco_fw/component/per/interfaces/per_blindnessDetectionData.hpp",
    ]

    SOURCE_DOMAINS: Dict[str, List[str]] = {
        "sit_cfm": [
            "reco_fw/component/sit/runnables/sit_s_runnableCfmRearCrossTraffic.cpp",
            "reco_fw/component/sit/runnables/sit_s_runnableCfmRearCrossTraffic.hpp",
        ],
        "sit_behavior_fm": [
            "reco_fw/component/sit/modules/behaviorStrategies/FM/sit_s_behaviorRctaBrakingFM.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/FM/sit_s_behaviorRctaWarningFM.hpp",
        ],
        "sit_behavior_tipl": [
            "reco_fw/component/sit/modules/behaviorStrategies/TIPL/laneChangeWarningTIPL/*.hpp",
        ],
        "sit_object": [
            "reco_fw/component/sit/modules/object/sit_s_objectSelector.hpp",
            "reco_fw/component/sit/modules/object/SensorDataProcessor/lcw/lf/predictor/sit_s_lcw*_ObjectSelector.hpp",
            "reco_fw/component/sit/modules/object/SensorDataProcessor/lcw/rf/predictor/sit_s_lcw*_ObjectSelector.hpp",
        ],
        "per_spp": [
            "reco_fw/component/per/runnables/per_sppRLocRunnable.cpp",
            "reco_fw/component/per/runnables/per_sppBdmRunnable.cpp",
            "reco_fw/component/per/runnables/per_sppStalinRunnable.cpp",
        ],
        "per_interfaces": [
            "reco_fw/component/per/interfaces/per_fusedObjectsDynamic.hpp",
            "reco_fw/component/per/interfaces/per_blindnessDetectionData.hpp",
            "reco_fw/component/per/interfaces/per_radarBoschGen5Feature.hpp",
        ],
        "fct_fsm": [
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssStateMachine.hpp",
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssActiveState.cpp",
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssPassiveState.cpp",
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssFcp.hpp",
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssState.hpp",
            "reco_fw/component/fct/modules/stateMachine/pss/fct_s_bsdStateMachine.hpp",
            "reco_fw/component/fct/modules/runCont/decisionMaker/decisionMakerController.hpp",
        ],
        "fct_behavior": [
            "reco_fw/component/fct/modules/behaviorManager/fct_s_behaviorManager.cpp",
            "reco_fw/component/fct/modules/behaviorManager/fct_s_behaviorManager.hpp",
            "reco_fw/component/fct/modules/fct_s_hmiSpecification.hpp",
        ],
        "fct_hmi": [
            "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.cpp",
            "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.hpp",
        ],
        "bsd_object_selector": [
            "reco_fw/component/sit/modules/objectSelector/sit_s_objectSelector.hpp",
        ],
        "bsd_warning_zone": [
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_warningZone.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_warningZone.cpp",
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_warningLine.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_warningLine.cpp",
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_innerVerticalLine.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/common/warningZone/sit_s_relevantObject.hpp",
        ],
        "bsd_suppression": [
            "reco_fw/component/fct/modules/hmi/brakeSuppresion/fct_s_brakeSuppresionHmi.hpp",
            "reco_fw/component/fct/modules/hmi/brakeSuppresion/fct_s_brakeSuppresionHmi.cpp",
            "reco_fw/component/fct/modules/stateMachine/interfaces/fct_s_pssSuppInterface.hpp",
        ],
        "bsd_tipl": [
            "reco_fw/component/sit/modules/behaviorStrategies/TIPL/laneChangeWarningTIPL/sit_s_behaviorLaneChangeWarningTIPL.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/TIPL/laneChangeWarningTIPL/sit_s_behaviorLaneChangeWarningTIPLHelper.hpp",
            "reco_fw/component/sit/modules/behaviorStrategies/TIPL/laneChangeWarningTIPL/sit_s_laneChangeWarningTIPLTypes.hpp",
        ],
        "bsd_params": [
            "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_bsdlca.hpp",
        ],
    }

    FUNC_KEYWORDS: Dict[str, List[str]] = {
        "BSD": [
            "BSD", "BlindSpotDetection", "BSD_Status", "BSD_Warn", "BSD_WarnL",
            "BSD_WarnR", "BSD_WarnLR", "BSD_WarnRR", "BSD_WarnLC", "BSD_WarnRC",
            "WarningZone", "Relevance", "Classification", "sit_s_objectSelector",
            "sit_s_warningZoneEval", "fct_s_brakeSuppresionHmi",
            "calcSuppressedWarningObjects", "evaluateWarningZone", "setRelevantObjects",
            "necessity", "dy", "dx", "euclideanDistance", "relativeVelocity",
            "existProb", "laneProb", "obstacleProb", "mobileProb",
            "bsd", "Bsd", "bsdStateMachine", "bsdSupp", "bsdWarningZone",
            "BsdAdaptiveSpeed", "VxvRefBsdlcaSwitchOn",
        ],
        "LCA": [
            "lca", "Lca", "LCA", "lcaStateMachine", "lcaSupp", "lcaWarningZone", "BSDLCA",
        ],
        "RCTA": [
            "rcta", "Rcta", "RCTA", "rctaStateMachine", "rctaBraking", "rctaWarning",
            "rearCrossTraffic", "rearCrossTrafficFM", "rctaNecessity",
        ],
        "RCTB": [
            "rctb", "Rctb", "RCTB", "rctbBraking", "rctbStateMachine", "rearCrossTrafficBraking",
        ],
        "FCTA": [
            "fcta", "Fcta", "FCTA", "fctaStateMachine", "fctaInfo", "fctaAeb", "fctaStartPrev", "fctaNecessity",
        ],
        "FCTB": [
            "fctb", "Fctb", "FCTB", "fctbState",
        ],
        "DOW": [
            "dow", "Dow", "DOW", "dowStateMachine", "doorOpeningFM", "doorOpening", "doorOpeningWarning",
        ],
        "RCW": [
            "rcw", "Rcw", "RCW", "rcwStateMachine", "rcw",
        ],
    }

    def __init__(self, source_root, config, project_root):
        self.source_root = Path(source_root)
        self.config = config
        self.project_root = Path(project_root)

    def get_key_source_files(self) -> list[str]:
        return list(self.KEY_SOURCE_FILES)

    def get_source_domains(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.SOURCE_DOMAINS.items()}

    def get_focus_files(self, focus: str) -> list[str]:
        _focus_files = {
            "alarm_logic": [
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_bsdStateMachine.hpp",
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssFcp.hpp",
                "apl/base/component/fct/config/padfct/padfct_s_par_gen.h",
            ],
            "calculation_chain": [
                "reco_fw/component/sit/modules/object/SensorDataProcessor/bsd/bandv/situ_evalBsdWarningZones/sit_s_evalBsdWarningZones.hpp",
                "apl/base/component/fct/config/padfct/padfct_s_par_gen.h",
                "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_bsdlca.hpp",
            ],
            "output_chain": [
                "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.cpp",
                "reco_fw/component/fct/runnables/hmi/fct_s_runnableHmi.hpp",
            ],
            "state_machine": [
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssStateMachine.hpp",
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssActiveState.cpp",
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssPassiveState.cpp",
                "reco_fw/component/fct/modules/stateMachine/pss/fct_s_pssFcp.hpp",
            ],
        }
        return list(_focus_files.get(focus, []))

    def get_func_keywords(self, func: str) -> list[str]:
        return list(self.FUNC_KEYWORDS.get(func, []))

    def get_constants_source_files(self) -> list[str]:
        return [
            "apl/base/component/fct/config/padfct/padfct_s_par_gen.h",
            "apl/base/component/fct/config/padfct/padfct_s_rctb.h",
            "apl/base/component/fct/config/padfct/padfct_s_fcta.h",
            "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_bsdlca.hpp",
            "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_fcta.hpp",
            "reco_fw/configuration/rearcorner/params/reco_fw_config_sit_rcta.hpp",
        ]

    def build_prompt_template(self, focus: str) -> dict[str, str]:
        return {
            "system": (
                "You are analyzing Bosch Gen5 ReCo (RCC1010 CornerBase) code for function {}.\n"
                "The codebase uses C++ with the following architecture layers:\n"
                "  - Flux: Radar signal processing layer\n"
                "  - DADDY: Bosch middleware for channel-based data routing (MF4 messages)\n"
                "  - PER: Perception layer (runnables, object selection, fused objects)\n"
                "  - SIT: Safety/Information layer (behavior strategies, object selectors)\n"
                "  - FCT: Function layer (state machines, behavior manager, HMI)\n"
                "  - PSS: Primary State Machine sub-layer within FCT\n"
            ).format(focus),
            "user": "Focus areas for '{}': {}".format(focus, ", ".join(self.get_focuses())),
            "instruction": (
                "Provide:\n"
                "1. Data flow description (PER -> SIT -> FCT)\n"
                "2. State machine transitions and triggers\n"
                "3. Suppression logic and PAD parameters\n"
                "4. DADDY/MF4 channel mappings\n"
                "5. Key variables and their lifecycles\n"
            ),
        }

    def build_overview_prompt(self) -> tuple[str, str]:
        return "", ""

    def get_priority_functions(self) -> list[str]:
        return ["BSD", "LCA", "RCTA", "RCTB", "FCTA", "FCTB", "DOW", "RCW"]

    def get_focuses(self) -> list[str]:
        return ["alarm_logic", "calculation_chain", "output_chain", "state_machine"]


@register_condition_extractor("gen5_reco_pl")
class Gen5RecoConditionExtractorAdapter(BaseConditionExtractorAdapter):
    """Condition extractor for Gen5 ReCo FCT state-machines and behavior logic."""

    FUNC_KEYWORDS = Gen5RecoCodeLearnerAdapter.FUNC_KEYWORDS
    SOURCE_DOMAINS = Gen5RecoCodeLearnerAdapter.SOURCE_DOMAINS

    def __init__(self, source_root, config, project_root):
        self.source_root = Path(source_root)
        self.config = config
        self.project_root = Path(project_root)

    def get_source_domains(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.SOURCE_DOMAINS.items()}

    def get_extraction_prompt(self, func_name: str) -> tuple[str, str]:
        return (
            "You are extracting conditional logic from Bosch Gen5 ReCo (RCC1010) C++ code. "
            "Focus on FCT state-machine guards, DADDY/MF4 channel conditions, PAD boolean parameters.",
            (
                "Extract all IF/ELSE/WHERE conditions from function: {}\n\n"
                "Source code:\n{source_code}\n\n"
                "Provide the output as a JSON array with entries:\n"
                "  {{ condition, trigger_context, source_location, related_domain }}"
            ).format(func_name),
        )

    def get_func_keywords(self, func: str) -> list[str]:
        return list(self.FUNC_KEYWORDS.get(func, []))

    def format_conditions(self, conditions: dict) -> str:
        if not conditions:
            return "No conditions extracted."
        lines = ["# Gen5 ReCo Extracted Conditions", ""]
        for cond in conditions:
            c = cond.get("condition", "N/A")
            trigger = cond.get("trigger_context", "")
            source = cond.get("source_location", "")
            domain = cond.get("related_domain", "Unknown")
            lines.append(f"- **{c}**")
            lines.append(f"  - Type: {domain}")
            lines.append(f"  - Context: {trigger}")
            lines.append(f"  - Source: {source}")
            lines.append("")
        return "\n".join(lines)


@register_signal_mapper("gen5_reco_pl")
class Gen5RecoSignalMapperAdapter(BaseSignalMapperAdapter):
    """Signal mapper for Gen5 ReCo. Gen5 uses MF4/DADDY channels instead of RteComMapping."""

    OUTPUT_SIGNALS: Dict[str, List[str]] = {
        "BSD": [
            "R_BSD_Status_S", "R_BSD_WarningL_S", "R_BSD_WarningR_S",
            "BSD_WarnL_S", "BSD_WarnR_S", "LBSDAndLCAWrnng", "BsdlcaWarnL",
            "BsdlcaWarnR", "BSDLevelII_WL", "BSDLevelII_WR", "hardBSDSwitch",
            "vEgoMes", "BSDLCAStatus",
        ],
        "LCA": [
            "R_BSD_Status_S", "R_BSD_WarningL_S", "R_BSD_WarningR_S",
            "BSD_WarnL_S", "BSD_WarnR_S", "LBSDAndLCAWrnng", "BsdlcaWarnL",
            "BsdlcaWarnR", "Bsdlca_left_warn", "Bsdlca_right_warn",
            "BSDLevelII_WL", "BSDLevelII_WR", "hardBSDSwitch", "vEgoMes",
            "BSDLCAStatus", "LCA_State",
        ],
        "RCTA": [
            "R_RCTA_Warn_L_S", "R_RCTA_Warn_R_S", "RCTA_BrmkgReq_L",
            "RCTA_BrmkgReq_R", "RCTA_State", "R_RCTA_WarnSts", "RCTA_Actv",
        ],
        "RCTB": [
            "RCTA_BrmkgReq_L", "RCTA_BrmkgReq_R", "RCTA_BrmkgReqVal_L",
            "RCTA_BrmkgReqVal_R", "RCTB_State",
        ],
        "FCTA": [
            "FCTA_Warn_FL", "FCTA_Warn_FR", "FCTA_BrmkgReq", "FCTA_BRK_TRIGGER",
            "FCTA_State", "FCTA_WarnSts_FL", "FCTA_WarnSts_FR",
        ],
        "DOW": [
            "R_DOW_Warn_L", "R_DOW_Warn_R", "DOW_State",
        ],
        "RCW": [
            "RCW_Trigger", "RCW_State", "RCW_TTC",
        ],
        "FCTB": [
            "FCTB_Warn_FL", "FCTB_Warn_FR", "FCTB_BRK_TRIGGER", "FCTB_State",
        ],
    }

    def __init__(self, source_root, output_dir, config, project_root):
        self.source_root = Path(source_root)
        self.output_dir = Path(output_dir)
        self.config = config
        self.project_root = Path(project_root)

    def extract_signal_mapping(self, source_root, output_dir) -> dict:
        return {}

    def extract_output_mapping(self, source_root, output_dir) -> dict:
        return {}

    def resolve_internal_to_can(self, var_name: str, mapping: dict, extra=None) -> list[str]:
        return []

    def resolve_can_to_internal(self, can_signal: str, mapping: dict) -> list[str]:
        return []

    def get_output_signals_for_function(self, func_name: str) -> list[str]:
        return list(self.OUTPUT_SIGNALS.get(func_name, []))
