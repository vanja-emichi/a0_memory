import asyncio
from helpers.extension import Extension
from plugins.a0_memory.helpers.memory import Memory
from agent import LoopData
from plugins.a0_memory.tools.memory_load import DEFAULT_THRESHOLD as DEFAULT_MEMORY_THRESHOLD
from helpers import dirty_json, errors, log, plugins, settings
from helpers.dirty_json import DirtyJson
from helpers.print_style import PrintStyle


DATA_NAME_TASK = "_recall_memories_task"
DATA_NAME_ITER = "_recall_memories_iter"


class RecallMemories(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):

        set = plugins.get_plugin_config("a0_memory", self.agent)

        # turned off in settings?
        if not set["memory_recall_enabled"]:
            return

        # every X iterations (or the first one) recall memories
        if loop_data.iteration % set["memory_recall_interval"] == 0:

            # show util message right away
            log_item = self.agent.context.log.log(
                type="util",
                heading="Searching memories...",
            )

            task = asyncio.create_task(
                self.search_memories(loop_data=loop_data, log_item=log_item, **kwargs)
            )
        else:
            task = None

        # set to agent to be able to wait for it
        self.agent.set_data(DATA_NAME_TASK, task)
        self.agent.set_data(DATA_NAME_ITER, loop_data.iteration)

    async def search_memories(self, log_item: log.LogItem, loop_data: LoopData, **kwargs):

        # cleanup
        extras = loop_data.extras_persistent
        if "memories" in extras:
            del extras["memories"]
        if "solutions" in extras:
            del extras["solutions"]


        set = plugins.get_plugin_config("a0_memory", self.agent)

        # get system message and chat history for util llm
        system = self.agent.read_prompt("memory.memories_query.sys.md")

        # call util llm to summarize conversation
        user_instruction = (
            loop_data.user_message.output_text() if loop_data.user_message else "None"
        )
        history = self.agent.history.output_text()[-set["memory_recall_history_len"]:]
        message = self.agent.read_prompt(
            "memory.memories_query.msg.md", history=history, message=user_instruction
        )

        # if query preparation by AI is enabled
        if set["memory_recall_query_prep"]:
            try:
                # call util llm to generate search query from the conversation
                query = await self.agent.call_utility_model(
                    system=system,
                    message=message,
                )
                query = query.strip()
                log_item.update(query=query) # no need for streaming here
            except Exception as e:
                err = errors.format_error(e)
                self.agent.context.log.log(
                    type="warning", heading="Recall memories extension error:", content=err
                )
                query = ""

            # no query, no search
            if not query:
                log_item.update(
                    heading="Failed to generate memory query",
                )
                return

        # otherwise use the message and history as query
        else:
            query = user_instruction + "\n\n" + history

        # if there is no query (or just dash by the LLM), do not continue
        if not query or len(query) <= 3:
            log_item.update(
                query="No relevant memory query generated, skipping search",
            )
            return

        # get memory database
        db = await Memory.get(self.agent)

        # === MULTI-QUERY: Extract additional keywords for broader recall ===
        extra_keywords = await self._extract_recall_keywords(
            user_instruction=user_instruction,
            history=history,
            log_item=log_item,
        )

        # Build list of all queries: main query + extracted keywords
        all_queries = [query] + extra_keywords
        if extra_keywords:
            PrintStyle.standard(f"Multi-query recall: main query + {len(extra_keywords)} keywords: {extra_keywords}")
            log_item.update(keywords=str(extra_keywords))

        # === Search memories using all queries ===
        all_memories = []
        all_solutions = []

        mem_filter = f"area == '{Memory.Area.MAIN.value}' or area == '{Memory.Area.FRAGMENTS.value}'"
        sol_filter = f"area == '{Memory.Area.SOLUTIONS.value}'"
        threshold = set["memory_recall_similarity_threshold"]

        for i, q in enumerate(all_queries):
            if not q or len(q.strip()) <= 2:
                continue

            # For keyword queries, use proportionally smaller limits
            if i == 0:
                # Main query gets full limits
                mem_limit = set["memory_recall_memories_max_search"]
                sol_limit = set["memory_recall_solutions_max_search"]
            else:
                # Keyword queries get proportional share of the limit
                kw_count = max(1, len(extra_keywords))
                mem_limit = max(3, set["memory_recall_memories_max_search"] // kw_count)
                sol_limit = max(2, set["memory_recall_solutions_max_search"] // kw_count)

            mems = await db.search_similarity_threshold(
                query=q.strip(),
                limit=mem_limit,
                threshold=threshold,
                filter=mem_filter,
            )
            all_memories.extend(mems)

            sols = await db.search_similarity_threshold(
                query=q.strip(),
                limit=sol_limit,
                threshold=threshold,
                filter=sol_filter,
            )
            all_solutions.extend(sols)

        # === Deduplicate by document metadata id, fallback to page_content ===
        memories = self._deduplicate_docs(all_memories)
        solutions = self._deduplicate_docs(all_solutions)

        if extra_keywords:
            PrintStyle.standard(
                f"Multi-query results: {len(all_memories)} raw -> {len(memories)} unique memories, "
                f"{len(all_solutions)} raw -> {len(solutions)} unique solutions"
            )

        if not memories and not solutions:
            log_item.update(
                heading="No memories or solutions found",
            )
            return

        # if post filtering is enabled
        if set["memory_recall_post_filter"]:
            # assemble an enumerated dict of memories and solutions for AI validation
            mems_list = {i: memory.page_content for i, memory in enumerate(memories + solutions)}

            # call AI to validate the memories
            try:
                filter = await self.agent.call_utility_model(
                    system=self.agent.read_prompt("memory.memories_filter.sys.md"),
                    message=self.agent.read_prompt(
                        "memory.memories_filter.msg.md",
                        memories=mems_list,
                        history=history,
                        message=user_instruction,
                    ),
                )
                filter_inds = dirty_json.try_parse(filter)

                # filter memories and solutions based on filter_inds
                filtered_memories = []
                filtered_solutions = []
                mem_len = len(memories)

                # process each index in filter_inds
                # make sure filter_inds is a list and contains valid integers
                if isinstance(filter_inds, list):
                    for idx in filter_inds:
                        if isinstance(idx, int):
                            if idx < mem_len:
                                # this is a memory
                                filtered_memories.append(memories[idx])
                            else:
                                # this is a solution, adjust index
                                sol_idx = idx - mem_len
                                if sol_idx < len(solutions):
                                    filtered_solutions.append(solutions[sol_idx])

                # replace original lists with filtered ones
                memories = filtered_memories
                solutions = filtered_solutions

            except Exception as e:
                err = errors.format_error(e)
                self.agent.context.log.log(
                    type="warning", heading="Failed to filter relevant memories", content=err
                )
                filter_inds = []


        # limit the number of memories and solutions
        memories = memories[: set["memory_recall_memories_max_result"]]
        solutions = solutions[: set["memory_recall_solutions_max_result"]]

        # log the search result
        log_item.update(
            heading=f"{len(memories)} memories and {len(solutions)} relevant solutions found",
        )

        memories_txt = "\n\n".join([mem.page_content for mem in memories]) if memories else ""
        solutions_txt = "\n\n".join([sol.page_content for sol in solutions]) if solutions else ""

        # log the full results
        if memories_txt:
            log_item.update(memories=memories_txt)
        if solutions_txt:
            log_item.update(solutions=solutions_txt)

        # place to prompt
        if memories_txt:
            extras["memories"] = self.agent.parse_prompt(
                "agent.system.memories.md", memories=memories_txt
            )
        if solutions_txt:
            extras["solutions"] = self.agent.parse_prompt(
                "agent.system.solutions.md", solutions=solutions_txt
            )

    async def _extract_recall_keywords(
        self,
        user_instruction: str,
        history: str,
        log_item: log.LogItem,
    ) -> list[str]:
        """Extract search keywords using fast pure-Python NLP.
        No LLM call needed - runs in microseconds instead of seconds."""
        STOPWORDS = {
            "a","an","the","and","or","but","in","on","at","to","for","of",
            "with","by","from","up","about","into","is","are","was","were",
            "be","been","have","has","had","do","does","did","will","would",
            "could","should","may","might","can","i","you","he","she","it",
            "we","they","what","which","who","this","that","these","those",
            "not","no","so","if","then","than","just","also","how","when",
            "where","why","please","help","need","want","get","use","make",
            "let","know","see","look","like","go","come","me","my","your",
            "its","our","their","there","here","now","more","some","any",
            "all","one","two","give","tell","show","yes","okay","thing",
        }
        try:
            text = user_instruction
            if not text or len(text.strip()) < 3:
                return []
            tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_.\-]{2,}", text)
            words = [
                t.lower() for t in tokens
                if t.lower() not in STOPWORDS and len(t) > 3
            ]
            seen = set()
            unique = []
            for w in words:
                if w not in seen:
                    seen.add(w)
                    unique.append(w)
            return unique[:4]
        except Exception as e:
            PrintStyle.warning(f"Keyword extraction failed: {e}")
            return []

    @staticmethod
    def _deduplicate_docs(docs: list) -> list:
        """Deduplicate documents by metadata id, with page_content fallback."""
        seen_ids = set()
        unique = []
        for doc in docs:
            # Primary: use document metadata id
            doc_id = doc.metadata.get("id") if hasattr(doc, "metadata") else None
            if doc_id:
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    unique.append(doc)
            else:
                # Fallback: use page_content hash for docs without id
                content_key = "_content_" + str(hash(doc.page_content))
                if content_key not in seen_ids:
                    seen_ids.add(content_key)
                    unique.append(doc)
        return unique
