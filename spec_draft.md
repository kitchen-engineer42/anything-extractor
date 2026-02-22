# General Discription

This is a project aiming to build a **self-adaptive** and **self-evolving** data extraction system. This extractor deals with tons of super long documents in professional scenarios like finance and law.

Github: https://github.com/kitchen-engineer42/anything-extractor.git

When starting a new task, there will be a number of sample documents and very few user input like 'extract all the useful data from these contracts' or 'find all information from these research reports so that we can know if these companies are worth invest'. No data schema, no pre-defined prompts, no few shots or any examples, no human annotation or ground-truth provided. The system should **grow** into an accurate, efficient and economical extraction system like it is tailored for this task.

The final thing that we are going to build and distribute to a number of industries and business scenarios is going to be extremely small, with only the core workflow, like a stem cell, yet with potiential of becoming a complicated system.

The system will keep evolving during its entire life span, updating its memory, learning new stuff and improving the accuracy and cost-efficiency of the system.

Some conceputal research on openclaw and EvoMap would be useful for the design. Please read:
https://github.com/openclaw/openclaw
https://evomap.ai/skill.md

All LLM calls for the system is provided by SiliconFlow. API key is provided in .env

The system can deal with tasks in both English and Chinese. When writing prompts, write in both languages. Language can be configured in .env

# Key Modules

The system should have three roles, a worker who actually carries out the extraction tasks, an observer who judges the outcome of extraction and also record human users' feedback, and finally a builder who modifies the entire system, including worker and observer.

## 1. Worker

Worker is essentially a set of workflows based on document parsing, chunking, LLM or code/regex based extracting and postprocessing. In production environment, worker deals with thousands of documents per day and extract hundreds of thousands of entries of data. Worker follows a principle of using the smallest and cheapest model capable for the task. If worker can run with a 30B-size model, it shouldn't run with a 70B-size model.

All worker agents are built, updated, modified, combined and removed by builder agents. The changes of worker agents should be recorded, like Git.

There is not fixed data schema defined by user, schema is agile and can be modified by builder agent all the time. **Keep it logical and agile.**

## 2. Observer

Obeserver is essentially the LLM-as-Judge for worker agents. Obeserver agents run on SOTA level models, with multi-modal capabilities if necessary. Observer agents judges the outcome from an end2end perspective. For example, if the worker agent runs in a workflow of 'document parsing - table recognition - data extraction - postprocessing', observer agent runs with a SOTA LLM with visual capabilities that can directly 'look' at the document page and give answers.

Observer agent is only here to observe. It is non-invasive. It should not change the output of worker agents. Observer agents should read the outcome, judge the correctness, record human users' feedback, and decide whether to call builder agents to fix and improve worker agents.

In the first few iterations, obeserver can be called very frequently because the outcome may have many errors. But as the iterations go, observer should only be called when witnessing low confidence and receiving direct negative feedback from user.

Observer should also do a small number of random sampling, even when the worker agents are working smoothly in later iterations, in case there are some catastrophic error or newly appeared corner cases.

## 3. Builder

Builder agents build, test and deploy extraction workflows when beginning new tasks. Builder agents modify, test and commit changes of extraction workflows when called by observer agents. Builder agents runs on SOTA level LLMs with exceptional coding abilities.

When need to fix problems of worker agents, builder agents are clever enough to distinguish corner cases from true design issues. When facing a logical problem, the builder agent should modify the extraction workflow, changing prompts and codes, adding or removing nodes from the flow, etc. When facing a corner cases, the builder should simply put it in a bases and build an RAG-like pipeline with high threshold, making it irrelevant to most cases.

Builder agent is also responsible of designing and improving a confidence mechanism for worker agents' output. Confidence level and iteration number decide when to call the observer agent to judge the outcome. The threshold is also decided by the builder agent.