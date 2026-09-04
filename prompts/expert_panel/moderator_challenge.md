## 问题
{case_context}

## 本轮参与的专家（{expert_count}位）的独立分析
{all_opinions}

---

作为研讨主持人，请:

1. 找出各专家分析中的**矛盾点**
2. 找出**遗漏的分析角度**（特别是: 是否有专家忽略了「条件检查表」中的某个条件?）
3. 对需要深入分析的专家提出**具体追问**（只针对本轮在场的专家: {panel_hint}）

输出JSON:
{{
  "contradictions": ["矛盾1描述", ...],
  "gaps": ["遗漏1描述", ...],
  "questions": {{
    {questions_template}
  }},
  "preliminary_consensus": "目前各专家的共识点",
  "key_dispute": "最关键的争议点"
}}