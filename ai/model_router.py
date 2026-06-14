# -*- coding: utf-8 -*-
"""
Dual-model router: local Ollama for simple tasks, remote Qwen3.5-27B for complex analysis.
Both use OpenAI-compatible API.

Remote model specs (Qwen3.5-27B-FP16):
  - Max context: 131,072 tokens (input + output combined)
  - Max concurrency: 24
  - Supports thinking mode (enable_thinking) and non-thinking mode
"""
import json
import time
from typing import Optional
from openai import OpenAI


class ModelRouter:
    """Route AI requests to the appropriate model based on task complexity."""

    REMOTE_MAX_CONTEXT = 131_072

    def __init__(self, config: dict):
        ai_cfg = config.get("ai", {})

        local_cfg = ai_cfg.get("local") or ai_cfg.get("gemma", {})
        remote_cfg = ai_cfg.get("remote") or ai_cfg.get("qwen", {})
        coder_cfg = ai_cfg.get("coder", {})

        self.local_client = OpenAI(
            base_url=local_cfg.get("base_url", "http://localhost:11434/v1"),
            api_key=local_cfg.get("api_key", "ollama"),
        )
        self.local_model = local_cfg.get("model", "qwen3:14b")

        # Remote client — graceful degradation when base_url or api_key is missing
        remote_base_url = remote_cfg.get("base_url")
        remote_api_key = remote_cfg.get("api_key")
        if remote_base_url and remote_api_key:
            self.remote_client = OpenAI(
                base_url=remote_base_url,
                api_key=remote_api_key,
            )
            self.remote_available = True
        else:
            self.remote_client = None
            self.remote_available = False
        self.remote_model = remote_cfg.get("model", "Qwen3.5-27B-FP16")

        # Coder model — for code generation tasks
        self.coder_client = OpenAI(
            base_url=coder_cfg.get("base_url", "http://10.190.161.39:8080/v1"),
            api_key=coder_cfg.get("api_key", "ollama"),
        )
        self.coder_model = coder_cfg.get("model", "qwen3-coder:30b")
        self.coder_max_tokens = coder_cfg.get("max_tokens", 2000)

        self.thinking_mode = ai_cfg.get("thinking", "off")

    def chat(
        self,
        messages: list[dict],
        complexity: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        response_format: Optional[dict] = None,
        thinking: bool = False,
    ) -> dict:
        """
        Send a chat completion request to the appropriate model.

        Args:
            messages: OpenAI-format message list.
            complexity: "simple" -> local, "complex" -> remote, "auto" -> heuristic.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            tools: Function calling tools (forces remote).
            response_format: Response format spec.
            thinking: Enable Qwen3.5 thinking mode for deep reasoning tasks.
        """
        if complexity == "auto":
            complexity = self._estimate_complexity(messages, tools)

        if complexity == "simple":
            client, model = self.local_client, self.local_model
        elif complexity == "coder":
            client, model = self.coder_client, self.coder_model
            # KV cache protection: cap max_tokens
            if max_tokens > self.coder_max_tokens:
                max_tokens = self.coder_max_tokens
        else:
            client, model = self.remote_client, self.remote_model

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format

        if complexity != "simple" and complexity != "coder":
            extra = {"chat_template_kwargs": {"enable_thinking": thinking}, "top_k": 20}
            if thinking:
                extra["presence_penalty"] = 1.5
                kwargs["temperature"] = 1.0
                kwargs["top_p"] = 0.95
            else:
                kwargs["top_p"] = 0.8
            kwargs["extra_body"] = extra
        elif complexity == "coder":
            # Coder: no thinking, low temperature for deterministic code
            if temperature > 0.3:
                temperature = 0.3
            kwargs["temperature"] = temperature
            kwargs["top_p"] = 0.9

        try:
            t0 = time.perf_counter()
            response = client.chat.completions.create(**kwargs)
            elapsed = time.perf_counter() - t0
            self._print_usage(response, model, complexity, elapsed)
            choice = response.choices[0]
            # qwen3 on Ollama puts output in reasoning field — use it as fallback
            message_content = choice.message.content or ""
            if not message_content and hasattr(choice.message, 'reasoning') and choice.message.reasoning:
                message_content = choice.message.reasoning
            result = {
                "content": message_content,
                "model": model,
                "complexity": complexity,
                "finish_reason": choice.finish_reason,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            }
            if choice.message.tool_calls:
                result["tool_calls"] = [
                    {
                        "function_name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    }
                    for tc in choice.message.tool_calls
                ]
            return result
        except Exception as e:
            if complexity == "simple":
                try:
                    kwargs["model"] = self.remote_model
                    kwargs.pop("extra_body", None)
                    kwargs["extra_body"] = {
                        "chat_template_kwargs": {"enable_thinking": False},
                        "top_k": 20,
                    }
                    kwargs["top_p"] = 0.8
                    t0 = time.perf_counter()
                    response = self.remote_client.chat.completions.create(**kwargs)
                    elapsed = time.perf_counter() - t0
                    self._print_usage(response, self.remote_model, "complex (fallback)", elapsed)
                    choice = response.choices[0]
                    fc_content = choice.message.content or ""
                    if not fc_content and hasattr(choice.message, 'reasoning') and choice.message.reasoning:
                        fc_content = choice.message.reasoning
                    return {
                        "content": fc_content,
                        "model": self.remote_model,
                        "complexity": "complex (fallback)",
                        "finish_reason": choice.finish_reason,
                    }
                except Exception as e2:
                    return {"content": "", "error": f"Both models failed: {e} / {e2}"}
            return {"content": "", "error": str(e)}

    def simple(self, prompt: str, system: str = "") -> str:
        """Quick helper for simple single-turn queries via local Ollama model."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = self.chat(messages, complexity="simple")
        return result.get("content", "")

    def complex(
        self,
        prompt: str,
        system: str = "",
        tools: Optional[list] = None,
        max_tokens: int = 16384,
        thinking: bool = False,
    ) -> dict:
        """Helper for complex analysis via remote Qwen3.5-27B model."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = self.chat(
            messages, complexity="complex", tools=tools,
            max_tokens=max_tokens, thinking=thinking,
        )

        if (
            thinking
            and not (result.get("content") or "").strip()
            and not result.get("error")
        ):
            # Qwen3 thinking mode occasionally emits the full response into
            # ``reasoning_content`` / ``<think>...</think>`` and leaves the
            # assistant ``content`` field empty.  Every downstream parser
            # (parse_json_from_llm, expert R2, code_learner extraction…) then
            # sees an empty string and gives up.  Retry once without thinking
            # so the model falls back to plain answer generation.
            import sys
            print(
                f"[model_router] thinking returned empty content "
                f"(finish={result.get('finish_reason')}, "
                f"tokens={result.get('usage', {}).get('completion_tokens')})"
                f"; retrying with thinking=False",
                file=sys.stderr,
            )
            result = self.chat(
                messages, complexity="complex", tools=tools,
                max_tokens=max_tokens, thinking=False,
            )

        return result

    @staticmethod
    def _print_usage(response, model: str, complexity: str, elapsed: float):
        usage = response.usage
        prompt_tok = usage.prompt_tokens if usage else 0
        completion_tok = usage.completion_tokens if usage else 0
        total_tok = prompt_tok + completion_tok
        gen_tps = completion_tok / elapsed if elapsed > 0 else 0
        total_tps = total_tok / elapsed if elapsed > 0 else 0
        finish = response.choices[0].finish_reason or "unknown"
        content_preview = (response.choices[0].message.content or "")[:120]
        truncated = finish == "length"
        ctx_pct = total_tok / ModelRouter.REMOTE_MAX_CONTEXT * 100 if model != "qwen3:14b" else 0

        print(f"\n{'─'*60}")
        print(f"[{model}]  complexity={complexity}  finish={finish}")
        if truncated:
            print(f"⚠️  OUTPUT TRUNCATED (finish_reason=length)")
        print(f"prompt_tokens     : {prompt_tok}")
        print(f"completion_tokens : {completion_tok}")
        print(f"total_tokens      : {total_tok}", end="")
        if ctx_pct > 0:
            print(f"  ({ctx_pct:.1f}% of 131K context)")
        else:
            print()
        print(f"elapsed           : {elapsed:.2f}s")
        print(f"generation speed  : {gen_tps:.1f} tok/s")
        print(f"overall throughput: {total_tps:.1f} tok/s")
        print(f"response preview  : {content_preview}{'...' if len(response.choices[0].message.content or '') > 120 else ''}")
        print(f"{'─'*60}")

    def _estimate_complexity(self, messages: list[dict], tools: Optional[list]) -> str:
        """Heuristic to decide simple vs complex."""
        if tools:
            return "complex"
        total_len = sum(len(m.get("content", "")) for m in messages)
        if total_len > 3000:
            return "complex"
        last_msg = messages[-1].get("content", "") if messages else ""
        complex_keywords = [
            "分析", "诊断", "为什么", "根因", "原因", "状态机",
            "analyze", "diagnose", "root cause", "state machine",
            "function calling", "多变量", "关联",
        ]
        if any(kw in last_msg.lower() for kw in complex_keywords):
            return "complex"
        return "simple"
