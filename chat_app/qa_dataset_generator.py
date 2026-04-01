"""
Q&A Dataset Generator for LLM Training

Converts Splunk documentation (specs, commands, PDFs) into Q&A format
suitable for fine-tuning LLMs or building instruction datasets.

Output formats:
- JSONL (for fine-tuning)
- CSV (for analysis)
- Parquet (for large-scale training)

Q&A Generation Strategy:
1. Extract structured content from documents
2. Generate questions based on content type:
   - Configuration specs: "How do I configure X?"
   - Commands: "What does the X command do?"
   - Reference docs: "What is X used for?"
3. Use document content as answers
4. Include metadata for filtering and traceability
"""

import json
import logging
import re
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass
from shared.conf_parser import parse_conf_stanzas, extract_app_metadata

logger = logging.getLogger(__name__)

@dataclass
class QAPair:
    """Represents a single question-answer pair with metadata"""
    question: str
    answer: str
    source_file: str
    source_type: str  # "spec", "command", "pdf", "conf"
    stanza: Optional[str] = None  # For .conf/.spec files
    app_name: Optional[str] = None
    app_type: Optional[str] = None
    confidence: float = 1.0  # Quality score (0-1)
    metadata: Optional[Dict] = None


class QADatasetGenerator:
    """Generate Q&A pairs from Splunk documentation"""

    def __init__(self, output_dir: str = "./qa_dataset", llm=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.qa_pairs: List[QAPair] = []
        self.llm = llm

    async def _generate_qa_with_llm(self, content_chunk: str, source_info: Dict) -> List[QAPair]:
        """
        Use an LLM to generate Q&A pairs from a chunk of text.
        """
        if not self.llm:
            return []

        pairs = []
        prompt = f"""
        You are an expert Splunk administrator. Based on the following configuration snippet from the file '{source_info.get("filename", "unknown")}', generate 3 insightful question-answer pairs a user might ask.
        The answer must be derived ONLY from the provided text.
        Format the output as a valid JSON list of objects, where each object has a "question" and "answer" key.

        **Configuration Snippet:**
        ```
        {content_chunk}
        ```

        **JSON Output:**
        """

        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            chain = ChatPromptTemplate.from_template(prompt) | self.llm | StrOutputParser()
            response = await chain.ainvoke({})

            # Extract JSON from the response
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
            if not json_match:
                logger.warning(f"LLM did not return a valid JSON list for chunk from {source_info.get('filename')}")
                return []

            generated_pairs = json.loads(json_match.group(0))

            for pair in generated_pairs:
                if "question" in pair and "answer" in pair:
                    pairs.append(QAPair(
                        question=pair["question"],
                        answer=pair["answer"],
                        source_file=source_info.get("filename", "unknown"),
                        source_type=source_info.get("source_type", "conf"),
                        stanza=source_info.get("stanza"),
                        app_name=source_info.get("app_name"),
                        app_type=source_info.get("app_type"),
                        confidence=0.85, # Higher confidence for LLM-generated from specific context
                        metadata=source_info.get("metadata", {})
                    ))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"LLM-based Q&A generation failed: {e}")

        return pairs

    async def generate_from_conf_file(self, file_path: str) -> List[QAPair]:
        """
        Generate Q&A pairs from a .conf or .conf.spec file.

        Strategy:
        - Each stanza becomes multiple Q&A pairs
        - Questions ask about configuration options
        - Answers include stanza content and context
        - LLM is used to generate additional Q&A if available.
        """
        pairs = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            stanzas = parse_conf_stanzas(content)
            metadata = extract_app_metadata(file_path)
            filename = Path(file_path).name

            # Extract base configuration name (e.g., "inputs.conf" from "inputs.conf.spec")
            conf_name = filename.replace('.spec', '')

            for stanza in stanzas:
                # Skip empty or comment-only stanzas
                if not stanza.content.strip() or stanza.content.strip().startswith('#'):
                    continue

                # Generate multiple rule-based Q&A pairs per stanza
                rule_based_pairs = self._generate_stanza_qa(
                    stanza=stanza,
                    conf_name=conf_name,
                    filename=filename,
                    metadata=metadata
                )
                pairs.extend(rule_based_pairs)

                # Generate additional Q&A pairs with LLM if available
                if self.llm:
                    source_info = {
                        "filename": filename,
                        "source_type": "conf" if ".spec" not in filename else "spec",
                        "stanza": stanza.name,
                        "app_name": metadata.get("app_name"),
                        "app_type": metadata.get("app_type"),
                        "metadata": metadata
                    }
                    # Use the full stanza content for the LLM
                    full_stanza_content = f"[{stanza.name}]\n{stanza.content}"
                    llm_pairs = await self._generate_qa_with_llm(full_stanza_content, source_info)
                    pairs.extend(llm_pairs)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Failed to generate Q&A from {file_path}: {e}")

        return pairs

    async def generate_from_spec_file(self, file_path: str) -> List[QAPair]:
        """
        Generate Q&A pairs from a .conf.spec file by calling the generic conf handler.
        """
        return await self.generate_from_conf_file(file_path)

    def _generate_stanza_qa(
        self,
        stanza,
        conf_name: str,
        filename: str,
        metadata: Dict
    ) -> List[QAPair]:
        """Generate multiple Q&A pairs for a single stanza"""
        pairs = []

        # Q1: General "What is this stanza for?"
        if stanza.name != "__preamble__":
            question = f"What is the [{stanza.name}] stanza in {conf_name} used for?"
            answer = self._format_stanza_answer(stanza, conf_name, include_context=True)
            pairs.append(QAPair(
                question=question,
                answer=answer,
                source_file=filename,
                source_type="spec",
                stanza=stanza.name,
                app_name=metadata.get("app_name"),
                app_type=metadata.get("app_type"),
                confidence=0.9,
                metadata=metadata
            ))

        # Q2: "How do I configure X?"
        if stanza.name != "__preamble__":
            question = f"How do I configure {stanza.name} in {conf_name}?"
            answer = self._format_stanza_answer(stanza, conf_name, include_context=False)
            pairs.append(QAPair(
                question=question,
                answer=answer,
                source_file=filename,
                source_type="spec",
                stanza=stanza.name,
                app_name=metadata.get("app_name"),
                app_type=metadata.get("app_type"),
                confidence=0.9,
                metadata=metadata
            ))

        # Q3: Extract specific settings and create Q&A for each
        settings = self._extract_settings(stanza.content)
        for setting_name, setting_desc in settings[:3]:  # Limit to top 3 settings per stanza
            question = f"What does the '{setting_name}' setting do in {conf_name} [{stanza.name}]?"
            answer = f"In {conf_name} [{stanza.name}]:\n\n{setting_desc}"
            pairs.append(QAPair(
                question=question,
                answer=answer,
                source_file=filename,
                source_type="spec",
                stanza=stanza.name,
                app_name=metadata.get("app_name"),
                app_type=metadata.get("app_type"),
                confidence=0.8,
                metadata=metadata
            ))

        return pairs

    def _format_stanza_answer(
        self,
        stanza,
        conf_name: str,
        include_context: bool = True
    ) -> str:
        """Format stanza content as an answer"""
        stanza_header = f"[{stanza.name}]" if stanza.name != "__preamble__" else "File Header"

        if include_context:
            answer = f"The {stanza_header} stanza in {conf_name} is used to configure:\n\n"
        else:
            answer = f"To configure {stanza_header} in {conf_name}, use:\n\n"

        answer += f"{stanza_header}\n{stanza.content.strip()}"
        return answer

    def _extract_settings(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract setting names and descriptions from stanza content.

        Returns: List of (setting_name, description) tuples
        """
        settings = []
        lines = content.split('\n')
        current_setting = None
        current_desc = []

        for line in lines:
            # Match setting definitions like "setting_name = <value>"
            setting_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.-]*)\s*=', line)
            if setting_match:
                # Save previous setting
                if current_setting and current_desc:
                    settings.append((current_setting, '\n'.join(current_desc)))

                # Start new setting
                current_setting = setting_match.group(1)
                current_desc = [line]
            elif current_setting:
                # Continue collecting description for current setting
                if line.strip().startswith('#') or line.strip().startswith('*'):
                    current_desc.append(line)
                elif line.strip() == '':
                    # Empty line might end the setting description
                    if current_desc:
                        settings.append((current_setting, '\n'.join(current_desc)))
                        current_setting = None
                        current_desc = []

        # Save last setting
        if current_setting and current_desc:
            settings.append((current_setting, '\n'.join(current_desc)))

        return settings

    async def generate_from_command_file(self, file_path: str) -> List[QAPair]:
        """
        Generate Q&A pairs from SPL command documentation.

        Strategy:
        - Extract command syntax and descriptions
        - Generate "What does X command do?" questions
        - Generate "How do I use X command?" questions
        - Use LLM to generate additional, more nuanced Q&A.
        """
        pairs = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            filename = Path(file_path).name
            command_name = filename.replace('.md', '').replace('.txt', '')

            # Q1: What does this command do?
            question = f"What does the {command_name} command do in Splunk?"
            answer = self._extract_command_description(content, command_name)
            if answer:
                pairs.append(QAPair(
                    question=question,
                    answer=answer,
                    source_file=filename,
                    source_type="command",
                    confidence=0.9
                ))

            # Q2: How do I use this command?
            question = f"How do I use the {command_name} command in Splunk?"
            answer = self._extract_command_syntax(content, command_name)
            if answer:
                pairs.append(QAPair(
                    question=question,
                    answer=answer,
                    source_file=filename,
                    source_type="command",
                    confidence=0.9
                ))

            # Q3: What are the arguments for this command?
            question = f"What arguments does the {command_name} command accept?"
            answer = self._extract_command_arguments(content, command_name)
            if answer:
                pairs.append(QAPair(
                    question=question,
                    answer=answer,
                    source_file=filename,
                    source_type="command",
                    confidence=0.8
                ))

            # Q4: Use LLM for more advanced Q&A
            if self.llm:
                source_info = {
                    "filename": filename,
                    "source_type": "command",
                    "stanza": command_name,
                }
                llm_pairs = await self._generate_qa_with_llm(content, source_info)
                pairs.extend(llm_pairs)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Failed to generate Q&A from command file {file_path}: {e}")

        return pairs

    def _extract_command_description(self, content: str, command_name: str) -> str:
        """Extract command description from documentation"""
        # Look for description section
        desc_patterns = [
            r'## Description\s*\n+(.*?)(?=\n##|\Z)',
            r'Description:\s*\n+(.*?)(?=\n##|\nSyntax:|\Z)',
            r'^(.+?)(?=\n##|\nSyntax:|\Z)'  # First paragraph
        ]

        for pattern in desc_patterns:
            match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if match:
                desc = match.group(1).strip()
                if desc and len(desc) > 20:
                    return f"The {command_name} command:\n\n{desc[:500]}"  # Limit to 500 chars

        return f"The {command_name} command in Splunk."

    def _extract_command_syntax(self, content: str, command_name: str) -> str:
        """Extract command syntax and usage examples"""
        # Look for syntax section
        syntax_patterns = [
            r'## Syntax\s*\n+```(.*?)```',
            r'Syntax:\s*\n+```(.*?)```',
            r'Usage:\s*\n+(.*?)(?=\n##|\Z)'
        ]

        for pattern in syntax_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                syntax = match.group(1).strip()
                if syntax:
                    return f"Syntax for {command_name}:\n\n```\n{syntax}\n```"

        # Fallback: look for code blocks
        code_blocks = re.findall(r'```(.*?)```', content, re.DOTALL)
        if code_blocks:
            return f"Usage example for {command_name}:\n\n```\n{code_blocks[0].strip()}\n```"

        return f"Use the {command_name} command in your Splunk search."

    def _extract_command_arguments(self, content: str, command_name: str) -> str:
        """Extract command arguments/options"""
        # Look for arguments section
        args_patterns = [
            r'## Arguments\s*\n+(.*?)(?=\n##|\Z)',
            r'## Options\s*\n+(.*?)(?=\n##|\Z)',
            r'## Parameters\s*\n+(.*?)(?=\n##|\Z)'
        ]

        for pattern in args_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                args = match.group(1).strip()
                if args and len(args) > 20:
                    return f"Arguments for {command_name}:\n\n{args[:500]}"

        return f"The {command_name} command accepts various arguments. Check the documentation for details."

    def generate_from_pdf(self, file_path: str, max_qa_per_page: int = 2) -> List[QAPair]:
        """
        Generate Q&A pairs from PDF documentation.

        Strategy:
        - Extract text from each page
        - Generate contextual questions based on content
        - Use paragraphs as answers
        """
        pairs = []

        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            filename = Path(file_path).name
            doc_name = filename.replace('.pdf', '')

            for page_num, page in enumerate(reader.pages):
                text = page.extract_text()
                if not text or len(text.strip()) < 50:
                    continue

                # Generate Q&A pairs from page content
                page_pairs = self._generate_pdf_page_qa(
                    text=text,
                    doc_name=doc_name,
                    filename=filename,
                    page_num=page_num + 1,
                    max_pairs=max_qa_per_page
                )
                pairs.extend(page_pairs)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Failed to generate Q&A from PDF {file_path}: {e}")

        return pairs

    def _generate_pdf_page_qa(
        self,
        text: str,
        doc_name: str,
        filename: str,
        page_num: int,
        max_pairs: int = 2
    ) -> List[QAPair]:
        """Generate Q&A pairs from a single PDF page"""
        pairs = []

        # Split into paragraphs
        paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]

        for i, paragraph in enumerate(paragraphs[:max_pairs]):
            # Generate contextual question
            question = self._generate_contextual_question(paragraph, doc_name)
            if question:
                pairs.append(QAPair(
                    question=question,
                    answer=paragraph,
                    source_file=filename,
                    source_type="pdf",
                    confidence=0.7,
                    metadata={"page": page_num}
                ))

        return pairs

    def _generate_contextual_question(self, text: str, doc_name: str) -> Optional[str]:
        """Generate a question based on text content"""
        # Look for key phrases that indicate topics
        if "configure" in text.lower() or "configuration" in text.lower():
            return f"How do I configure {doc_name}?"
        elif "install" in text.lower() or "installation" in text.lower():
            return f"How do I install {doc_name}?"
        elif "example" in text.lower():
            return f"Can you show an example of using {doc_name}?"
        elif "troubleshoot" in text.lower() or "error" in text.lower():
            return f"How do I troubleshoot {doc_name}?"
        else:
            # Generic question
            return f"What is {doc_name} used for?"

    def add_qa_pair(self, pair: QAPair):
        """Add a Q&A pair to the dataset"""
        self.qa_pairs.append(pair)

    def save_jsonl(self, filename: str = "qa_dataset.jsonl"):
        """Save dataset as JSONL (suitable for fine-tuning)"""
        output_path = self.output_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            for pair in self.qa_pairs:
                # Format for instruction fine-tuning
                record = {
                    "instruction": pair.question,
                    "input": "",
                    "output": pair.answer,
                    "metadata": {
                        "source_file": pair.source_file,
                        "source_type": pair.source_type,
                        "confidence": pair.confidence,
                        **(pair.metadata or {})
                    }
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        logger.info(f"Saved {len(self.qa_pairs)} Q&A pairs to {output_path}")
        return output_path

    def save_csv(self, filename: str = "qa_dataset.csv"):
        """Save dataset as CSV (for analysis)"""
        import csv

        output_path = self.output_dir / filename

        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'question', 'answer', 'source_file', 'source_type',
                'stanza', 'app_name', 'app_type', 'confidence'
            ])

            for pair in self.qa_pairs:
                writer.writerow([
                    pair.question,
                    pair.answer,
                    pair.source_file,
                    pair.source_type,
                    pair.stanza or '',
                    pair.app_name or '',
                    pair.app_type or '',
                    pair.confidence
                ])

        logger.info(f"Saved {len(self.qa_pairs)} Q&A pairs to {output_path}")
        return output_path

    def save_openai_format(self, filename: str = "qa_dataset_openai.jsonl"):
        """Save dataset in OpenAI fine-tuning format"""
        output_path = self.output_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            for pair in self.qa_pairs:
                # OpenAI chat completion format
                record = {
                    "messages": [
                        {"role": "system", "content": "You are a Splunk expert assistant."},
                        {"role": "user", "content": pair.question},
                        {"role": "assistant", "content": pair.answer}
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        logger.info(f"Saved {len(self.qa_pairs)} Q&A pairs to {output_path} (OpenAI format)")
        return output_path

    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        stats = {
            "total_pairs": len(self.qa_pairs),
            "by_source_type": {},
            "by_confidence": {},
            "avg_question_length": 0,
            "avg_answer_length": 0
        }

        if not self.qa_pairs:
            return stats

        # Group by source type
        for pair in self.qa_pairs:
            stats["by_source_type"][pair.source_type] = stats["by_source_type"].get(pair.source_type, 0) + 1

        # Calculate averages
        stats["avg_question_length"] = sum(len(p.question) for p in self.qa_pairs) / len(self.qa_pairs)
        stats["avg_answer_length"] = sum(len(p.answer) for p in self.qa_pairs) / len(self.qa_pairs)

        # Confidence distribution
        high_conf = sum(1 for p in self.qa_pairs if p.confidence >= 0.9)
        med_conf = sum(1 for p in self.qa_pairs if 0.7 <= p.confidence < 0.9)
        low_conf = sum(1 for p in self.qa_pairs if p.confidence < 0.7)

        stats["by_confidence"] = {
            "high (>=0.9)": high_conf,
            "medium (0.7-0.9)": med_conf,
            "low (<0.7)": low_conf
        }

        return stats

    async def ingest_qa_pairs(self, vector_store, qa_pairs: List[QAPair]) -> int:
        """
        Takes a list of QAPair objects and ingests them into ChromaDB.
        """
        if not qa_pairs:
            logger.warning("No Q&A pairs provided to ingest.")
            return 0

        batch_size = 100
        total_ingested = 0

        logger.info(f"Starting ingestion of {len(qa_pairs)} Q&A pairs...")

        for i in range(0, len(qa_pairs), batch_size):
            batch = qa_pairs[i:i + batch_size]

            texts_to_ingest = []
            metadatas_to_ingest = []

            for pair in batch:
                text = f"Question: {pair.question}\n\nAnswer: {pair.answer}"
                texts_to_ingest.append(text)

                metadata = {
                    "source": pair.source_file,
                    "kind": "generated_qa_v1",  # Use versioned identifier
                    "stanza": pair.stanza or "general",
                    "generator": "run_ingest_all.py",
                    **(pair.metadata or {})
                }
                metadatas_to_ingest.append(metadata)

            try:
                vector_store.add_texts(texts=texts_to_ingest, metadatas=metadatas_to_ingest)
                total_ingested += len(texts_to_ingest)
                logger.info(f"Ingested batch {i // batch_size + 1}, containing {len(texts_to_ingest)} pairs.")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.error(f"Error during batch ingestion: {e}")

        return total_ingested
