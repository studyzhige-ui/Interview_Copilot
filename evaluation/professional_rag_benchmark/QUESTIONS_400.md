# 400 source-grounded question candidates

These are programmatic candidates for review, not independently reviewed gold answers.
Each quote is an exact span from the downloaded original text. Offsets are character offsets in the extracted UTF-8 text.

## PROF-0001 · single_fact

**Question:** Does merely calling an asyncio coroutine schedule it to run?

**Reference answer:** Note that simply calling a coroutine will not schedule it to be executed:

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `745:818` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Note that simply calling a coroutine will not schedule it to
be executed:

Split: `dev` · Review: `programmatic_candidate`

## PROF-0002 · single_fact

**Question:** What exception is raised when an asyncio task is cancelled?

**Reference answer:** When a task is cancelled, asyncio.CancelledError will be raised in the task at the next opportunity.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `7157:7257` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: When a task is cancelled,
asyncio.CancelledError
will be raised
in the task at the next opportunity.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0003 · single_fact

**Question:** According to Python asyncio Tasks, what can Timeout context managers do?

**Reference answer:** Timeout context managers can be safely nested.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `22352:22398` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Timeout context managers can be safely nested.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0004 · single_fact

**Question:** According to Python asyncio Tasks, what does the document state about Tasks?

**Reference answer:** Tasks are used to run coroutines in event loops.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `32015:32063` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks are used to run coroutines in event loops.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0005 · single_fact

**Question:** According to Python asyncio Tasks, what can Tasks do?

**Reference answer:** Tasks can easily and safely be cancelled.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `7115:7156` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks can easily and safely be cancelled.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0006 · single_fact

**Question:** What do React Effects let a component synchronize with?

**Reference answer:** let you run some code after rendering so that you can synchronize your component with some system outside of React.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `316:431` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: let you run some code after rendering so that you can synchronize your component with some system outside of React.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0007 · single_fact

**Question:** According to React Synchronizing with Effects, what does the document state about Synchronizing with an external system?

**Reference answer:** Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `9458:9576` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0008 · single_fact

**Question:** According to React Synchronizing with Effects, what can The dependency array do?

**Reference answer:** The dependency array can contain multiple dependencies.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `13850:13905` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: The dependency array can contain multiple dependencies.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0009 · single_fact

**Question:** According to React Synchronizing with Effects, what does the guidance require of The cleanup function?

**Reference answer:** The cleanup function should stop or undo whatever the Effect was doing.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `20749:20820` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: The cleanup function should stop or undo whatever the Effect was doing.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0010 · single_fact

**Question:** According to React, what causes a buying action?

**Reference answer:** Buying is not caused by rendering; it’s caused by a specific interaction.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `30783:30856` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Buying is not caused by rendering; it’s caused by a specific interaction.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0011 · single_fact

**Question:** According to React Synchronizing with Effects, what does the guidance require of The animation?

**Reference answer:** The animation should only play once when the component appears for the first time.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `9769:9851` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: The animation should only play once when the component appears for the first time.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0012 · single_fact

**Question:** According to React Synchronizing with Effects, what does the document state about Connecting to a server?

**Reference answer:** Connecting to a server is not a pure calculation (it’s a side effect) so it can’t happen during rendering.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `1677:1783` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Connecting to a server is not a pure calculation (it’s a side effect) so it can’t happen during rendering.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0013 · single_fact

**Question:** How many transaction isolation levels does the SQL standard define?

**Reference answer:** standard defines four levels of transaction isolation.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `576:630` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: standard defines four levels of transaction isolation.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0014 · single_fact

**Question:** What outcome does Serializable isolation guarantee for concurrent transactions?

**Reference answer:** The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `631:876` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0015 · single_fact

**Question:** According to PostgreSQL Transaction Isolation, what can More complex usage do?

**Reference answer:** More complex usage can produce undesirable results in Read Committed mode.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `8861:8935` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: More complex usage can produce undesirable results in Read Committed mode.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0016 · single_fact

**Question:** According to PostgreSQL Transaction Isolation, what can Consistent use of Serializable transactions do?

**Reference answer:** Consistent use of Serializable transactions can simplify development.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `19478:19547` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: Consistent use of Serializable transactions can simplify development.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0017 · single_fact

**Question:** According to PostgreSQL Transaction Isolation, what does the document state about The Serializable isolation level?

**Reference answer:** The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `23422:23642` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0018 · single_fact

**Question:** How does the SQL standard define the three isolation levels below Serializable?

**Reference answer:** The other three levels are defined in terms of phenomena, resulting from interaction between concurrent transactions, which must not occur at each level.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `877:1030` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The other three levels are defined in terms of phenomena, resulting from interaction between concurrent transactions, which must not occur at each level.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0019 · single_fact

**Question:** How does LangChain define an agent?

**Reference answer:** An agent is a model calling tools in a loop until a given task is complete.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `0:75` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: An agent is a model calling tools in a loop until a given task is complete.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0020 · single_fact

**Question:** According to LangChain Agents, what can Hooks receive the current state and do?

**Reference answer:** Hooks receive the current state and can return a dict of updates to merge back into it.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `9860:9947` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Hooks receive the current state and can return a dict of updates to merge back into it.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0021 · single_fact

**Question:** What role does middleware play in customizing a LangChain agent?

**Reference answer:** Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `23252:23413` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0022 · single_fact

**Question:** According to LangChain Agents, what does the document state about Agents?

**Reference answer:** Agents are especially useful when they can take action rather than just generate text.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `24302:24388` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Agents are especially useful when they can take action rather than just generate text.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0023 · single_fact

**Question:** According to LangChain Agents, what does the document state about Common patterns?

**Reference answer:** Common patterns are prebuilt as first-class middleware.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `23471:23526` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Common patterns are prebuilt as first-class middleware.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0024 · single_fact

**Question:** What components make up an agent harness in this LangChain guide?

**Reference answer:** A harness is everything around that loop: the prompt, the tools, and any middleware that shapes the model’s behavior.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `76:193` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: A harness is everything around that loop: the prompt, the tools, and any middleware that shapes the model’s behavior.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0025 · single_fact

**Question:** Under the MCP tools specification, what can servers expose to language models?

**Reference answer:** The Model Context Protocol (MCP) allows servers to expose tools that can be invoked by language models.

**Evidence:**

- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `0:103` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: The Model Context Protocol (MCP) allows servers to expose tools that can be invoked by
language models.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0026 · single_fact

**Question:** Does MCP tool discovery support pagination?

**Reference answer:** This operation supports pagination .

**Evidence:**

- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `1411:1447` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: This operation supports
pagination
.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0027 · single_fact

**Question:** Which request does an MCP client send to discover available tools?

**Reference answer:** To discover available tools, clients send a tools/list request.

**Evidence:**

- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `1347:1410` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: To discover available tools, clients send a
tools/list
request.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0028 · single_fact

**Question:** What does the MCP tools specification recommend for human oversight of tool invocations?

**Reference answer:** For trust & safety and security, there SHOULD always be a human in the loop with the ability to deny tool invocations.

**Evidence:**

- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `708:826` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: For trust & safety and security, there
SHOULD
always
be a human in the loop with the ability to deny tool invocations.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0029 · single_fact

**Question:** How are individual MCP tools identified and described?

**Reference answer:** Each tool is uniquely identified by a name and includes metadata describing its schema.

**Evidence:**

- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `229:316` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: Each tool is uniquely identified by
a name and includes metadata describing its schema.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0030 · single_fact

**Question:** How does WHO define patient safety?

**Reference answer:** Patient safety is defined as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `343:514` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Patient safety is
defined
as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."

Split: `dev` · Review: `programmatic_candidate`

## PROF-0031 · single_fact

**Question:** What is sepsis according to WHO?

**Reference answer:** Sepsis is a serious condition that happens when the body’s immune system has an extreme response to an infection.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1831:1944` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Sepsis is a serious condition that happens when the body’s immune system has an extreme response to an infection.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0032 · single_fact

**Question:** What are the reported consequences of health care-associated infections?

**Reference answer:** health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1583:1816` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths

Split: `dev` · Review: `programmatic_candidate`

## PROF-0033 · single_fact

**Question:** According to WHO Patient safety, what can Failure to correctly identify patients do?

**Reference answer:** Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `3815:3940` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0034 · single_fact

**Question:** What is the general WCAG requirement for non-text content presented to users?

**Reference answer:** non-text content that is presented to the user has a text alternative that serves the equivalent purpose

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `292:396` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: non-text content
that is presented to the user has a
text alternative
that serves the equivalent purpose

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0035 · single_fact

**Question:** What alternatives does WCAG require for CAPTCHA that uses non-text content?

**Reference answer:** If the purpose of non-text content is to confirm that content is being accessed by a person rather than a computer, then text alternatives that identify and describe the purpose of the non-text content are provided, and alternative forms of CAPTCHA using output modes for different types of sensory perception are provided

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `1263:1588` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: If the purpose of non-text content is to confirm that content is being accessed by
 a person rather than a computer, then text alternatives that identify and describe
 the purpose of the non-text content are provided, and alternative forms of CAPTCHA
 using output modes for different types of sensory perception are provided

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0036 · single_fact

**Question:** According to WCAG 2.2 Non-text Content, what does the guidance require of Text alternatives and equivalents?

**Reference answer:** Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `4262:4402` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0037 · single_fact

**Question:** According to WCAG 2.2 Non-text Content, what does the document state about An image of a chart?

**Reference answer:** An image of a chart is described in text in the paragraph after the chart.

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `28875:28949` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: An image of a chart is described in text in the paragraph after the chart.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0038 · single_fact

**Question:** Which two strategies does Investor.gov name for managing investing risk?

**Reference answer:** Two important strategies for managing investing risk are asset allocation and diversification.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `4116:4210` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Two important strategies for managing investing risk are asset allocation and diversification.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0039 · single_fact

**Question:** What is asset allocation according to Investor.gov?

**Reference answer:** Asset allocation involves dividing your investments among different “asset classes”, such as stocks , bonds , and cash.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `4211:4330` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Asset allocation involves dividing your investments among different “asset classes”, such as
stocks
,
bonds
, and cash.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0040 · single_fact

**Question:** According to SEC Introduction to Investing, what can Diversification  do?

**Reference answer:** Diversification can help reduce your losses if the market drops, because when different sectors may be down, other sectors may rally and allow a diversified investor to break even or even post gains.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `5425:5624` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Diversification can help reduce your losses if the market drops, because when different sectors may be down, other sectors may rally and allow a diversified investor to break even or even post gains.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0041 · single_fact

**Question:** According to SEC Introduction to Investing, what does the document state about Funds for short-term goals?

**Reference answer:** Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `8041:8191` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0042 · single_fact

**Question:** According to SEC Introduction to Investing, what does the document state about Regular investing?

**Reference answer:** Regular investing means that you put a set dollar amount or a set percentage of your income into your investment accounts.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `2574:2696` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Regular investing means that you put a set dollar amount or a set percentage of your income into your investment accounts.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0043 · single_fact

**Question:** According to SEC Introduction to Investing, what does the document state about A savings account?

**Reference answer:** A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `602:722` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0044 · single_fact

**Question:** Vue 的浅层 ref 仅追踪哪种访问？

**Reference answer:** 对于浅层 ref，只有 .value 的访问会被追踪。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `4751:4778` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 对于浅层 ref，只有
.value
的访问会被追踪。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0045 · single_fact

**Question:** Vue 响应式对象与普通对象相比，属性访问和修改有什么区别？

**Reference answer:** 响应式对象是 JavaScript 代理 ，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `5551:5629` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 响应式对象是
JavaScript 代理
，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0046 · single_fact

**Question:** 根据《Vue 响应式基础》，和组件实例上的其他属性一样，方法也可以采取什么做法？

**Reference answer:** 和组件实例上的其他属性一样，方法也可以在模板上被访问。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `3964:3991` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 和组件实例上的其他属性一样，方法也可以在模板上被访问。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0047 · single_fact

**Question:** 根据《Vue 响应式基础》，浅层 ref可以采取什么做法？

**Reference answer:** 浅层 ref 可以用于避免对大型数据的响应性开销来优化性能、或者有外部库管理其内部状态的情况。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `4778:4825` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 浅层 ref 可以用于避免对大型数据的响应性开销来优化性能、或者有外部库管理其内部状态的情况。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0048 · single_fact

**Question:** Kubernetes Deployment 的 pod-template-hash 标签起什么作用？

**Reference answer:** 此标签可确保 Deployment 的子 ReplicaSet 不重叠。

**Evidence:**

- [kubernetes-deployment-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/controllers/deployment/) · extracted text `4019:4055` · SHA-256 `3b75a6fa4bbaebdd9b87f6262527e5d906976e08043734590f327eb3ecb8c15e`: 此标签可确保 Deployment 的子 ReplicaSet 不重叠。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0049 · single_fact

**Question:** Kubernetes Deployment 更新时默认至少保持多少比例的所需 Pod 运行？

**Reference answer:** Deployment 可确保在更新时仅关闭一定数量的 Pod。默认情况下，它确保至少所需 Pod 的 75% 处于运行状态（最大不可用比例为 25%）。

**Evidence:**

- [kubernetes-deployment-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/controllers/deployment/) · extracted text `5749:5825` · SHA-256 `3b75a6fa4bbaebdd9b87f6262527e5d906976e08043734590f327eb3ecb8c15e`: Deployment 可确保在更新时仅关闭一定数量的 Pod。默认情况下，它确保至少所需
Pod 的 75% 处于运行状态（最大不可用比例为 25%）。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0050 · single_fact

**Question:** 阿里云百炼列出的三种核心应用构建模式是什么？

**Reference answer:** 三种核心应用构建模式：智能体（Agent）、工作流（Workflow） 和高代码应用 。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `52:97` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 三种 核心应用构建模式：智能体（Agent）、工作流（Workflow） 和高代码应用 。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0051 · single_fact

**Question:** 百炼智能体应用如何理解用户意图并完成任务？

**Reference answer:** 由提示词驱动，能够自主理解用户意图、制定决策，并调用知识库、MCP 服务等外部工具来完成任务。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `175:222` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 由提示词驱动，能够自主理解用户意图、制定决策，并调用知识库、MCP 服务等外部工具来完成任务。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0052 · single_fact

**Question:** 百炼工作流应用如何组织多步骤复杂任务？

**Reference answer:** 通过可视化节点编排，能够将多步骤复杂任务串联成稳定可控、可复现的执行链路。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `278:315` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 通过可视化节点编排，能够将多步骤复杂任务串联成稳定可控、可复现的执行链路。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0053 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？

**Reference answer:** 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0054 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，劳动合同期限三个月以上不满一年的，试用期有哪些禁止性规定？

**Reference answer:** 劳动合同期限三个月以上不满一年的，试用期不得超过一个月；劳动合同期限一年以上不满三年的，试用期不得超过二个月；三年以上固定期限和无固定期限的劳动合同，试用期不得超过六个月。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `2444:2530` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动合同期限三个月以上不满一年的，试用期不得超过一个月；劳动合同期限一年以上不满三年的，试用期不得超过二个月；三年以上固定期限和无固定期限的劳动合同，试用期不得超过六个月。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0055 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，劳动者在试用期内提前三日通知用人单位可以采取什么做法？

**Reference answer:** 劳动者在试用期内提前三日通知用人单位，可以解除劳动合同。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `4204:4232` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动者在试用期内提前三日通知用人单位，可以解除劳动合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0056 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，用人单位违反集体合同，侵犯职工劳动权益的，工会可以采取什么做法？

**Reference answer:** 用人单位违反集体合同，侵犯职工劳动权益的，工会可以依法要求用人单位承担责任；因履行集体合同发生争议，经协商解决不成的，工会可以依法申请仲裁、提起诉讼。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `7212:7287` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 用人单位违反集体合同，侵犯职工劳动权益的，工会可以依法要求用人单位承担责任；因履行集体合同发生争议，经协商解决不成的，工会可以依法申请仲裁、提起诉讼。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0057 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，劳动行政部门的工作人员进行监督检查有哪些要求？

**Reference answer:** 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9609:9646` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0058 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，非全日制用工小时计酬标准有哪些禁止性规定？

**Reference answer:** 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9060:9099` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0059 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，用人单位有哪些要求？

**Reference answer:** 用人单位应当研究工会的意见，并将处理结果书面通知工会。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `5620:5647` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 用人单位应当研究工会的意见，并将处理结果书面通知工会。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0060 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，固定期限劳动合同指什么？

**Reference answer:** 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `1522:1555` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0061 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，用工单位有哪些禁止性规定？

**Reference answer:** 用工单位不得将被派遣劳动者再派遣到其他用人单位。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `8145:8169` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 用工单位不得将被派遣劳动者再派遣到其他用人单位。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0062 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，除本法第二十二条和第二十三条规定的情形外，用人单位有哪些禁止性规定？

**Reference answer:** 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `3337:3380` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0063 · single_fact

**Question:** 根据《中华人民共和国劳动合同法》，用人单位依照本法有关规定有哪些要求？

**Reference answer:** 用人单位依照本法有关规定应当向劳动者支付经济补偿的，在办结工作交接时支付。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `6642:6679` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 用人单位依照本法有关规定应当向劳动者支付经济补偿的，在办结工作交接时支付。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0064 · single_fact

**Question:** 根据《中华人民共和国民法典》第八条，民事主体从事民事活动有哪些禁止性规定？

**Reference answer:** 第八条民事主体从事民事活动，不得违反法律，不得违背公序良俗。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `2488:2519` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第八条　民事主体从事民事活动，不得违反法律，不得违背公序良俗。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0065 · single_fact

**Question:** 根据《中华人民共和国民法典》第一百六十一条，民事主体可以采取什么做法？

**Reference answer:** 第一百六十一条民事主体可以通过代理人实施民事法律行为。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `15842:15870` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第一百六十一条　民事主体可以通过代理人实施民事法律行为。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0066 · single_fact

**Question:** 根据《中华人民共和国民法典》第四百二十七条，设立质权，当事人有哪些要求？

**Reference answer:** 第四百二十七条设立质权，当事人应当采用书面形式订立质押合同。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `39964:39995` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第四百二十七条　设立质权，当事人应当采用书面形式订立质押合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0067 · single_fact

**Question:** 根据《中华人民共和国民法典》第七百八十九条，建设工程合同有哪些要求？

**Reference answer:** 第七百八十九条建设工程合同应当采用书面形式。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `74740:74763` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第七百八十九条　建设工程合同应当采用书面形式。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0068 · single_fact

**Question:** 根据《中华人民共和国民法典》第九百九十二条，人格权有哪些禁止性规定？

**Reference answer:** 第九百九十二条人格权不得放弃、转让或者继承。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `94789:94812` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百九十二条　人格权不得放弃、转让或者继承。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0069 · single_fact

**Question:** 根据《中华人民共和国民法典》第九百三十三条，委托人或者受托人可以采取什么做法？

**Reference answer:** 第九百三十三条委托人或者受托人可以随时解除委托合同。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `88977:89004` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百三十三条　委托人或者受托人可以随时解除委托合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0070 · single_fact

**Question:** 根据《中华人民共和国民法典》第四百条，设立抵押权，当事人有哪些要求？

**Reference answer:** 第四百条设立抵押权，当事人应当采用书面形式订立抵押合同。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `37136:37165` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第四百条　设立抵押权，当事人应当采用书面形式订立抵押合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0071 · single_fact

**Question:** 《抗菌药物临床应用管理办法》所称抗菌药物包括哪些用途，不包括哪些药物？

**Reference answer:** 本办法所称抗菌药物是指治疗细菌、支原体、衣原体、立克次体、螺旋体、真菌等病原微生物所致感染性疾病病原的药物，不包括治疗结核病、 寄生虫病和各种病毒所致感染性疾病的药物以及具有抗菌作用的中药制剂。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `200:304` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 本办法所称抗菌药物是指治疗细菌、支

原体、衣原体、立克次体、螺旋体、真菌等病原微生

物所致感染性疾病病原的药物，不包括治疗结核病、

寄生虫病和各种病毒所致感染性疾病的药物以及具

有抗菌作用的中药制剂。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0072 · single_fact

**Question:** 抗菌药物临床应用按哪些因素分级，分为哪三级？

**Reference answer:** 抗菌药物临床应用实行分级管理。根据安全性、疗效、细菌耐药性、价格等因素，将抗菌药物分为三级：非限制使用级、限制使用级与特殊使用级。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `493:564` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 抗菌药物临床应用实行分级管理。根据

安全性、疗效、细菌耐药性、价格等因素，将抗菌药

物分为三级：非限制使用级、限制使用级与特殊使用

级。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0073 · single_fact

**Question:** 抗菌药物临床应用应遵循什么原则？

**Reference answer:** 抗菌药物临床应用应当遵循安全、有效、经济的原则。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `460:486` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 抗菌药物临床应用应当遵循安全、有

效、经济的原则。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0074 · single_fact

**Question:** 《医院感染管理办法》如何定义医院感染管理？

**Reference answer:** 医院感染管理是各级卫生行政部门、医疗机构及医务人员针对诊疗活动中存在的医院感染、 医源性感染及相关的危险因素进行的预防、诊断和控制活动。

**Evidence:**

- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `194:267` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 医院感染管理是各级卫生行政部门、医

疗机构及医务人员针对诊疗活动中存在的医院感染、

医源性感染及相关的危险因素进行的预防、诊断和控

制活动。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0075 · single_fact

**Question:** 《医院感染管理办法》对住院床位总数在100张以上的医院设置感染管理组织有何要求？

**Reference answer:** 住院床位总数在100 张以上的医院应当设立医院感染管理委员会和独立的医院感染管理部门。

**Evidence:**

- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `598:682` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 住院床位总数在100 张以上的医院应当

设立医院感染管理委员会和独立的医院感染管理部




- 2 -

 国家卫生健康委员会发布
 国家卫生健康委员会规章

门。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0076 · single_fact

**Question:** 《医务人员手卫生规范》如何定义手卫生？

**Reference answer:** 为医务人员在从事职业活动过程中的洗手、卫生手消毒和外科手消毒的总称。

**Evidence:**

- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `1881:1915` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 为医务人员在从事职业活动过程中的洗手、卫生手消毒和外科手消毒的总称。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0077 · single_fact

**Question:** 《医务人员手卫生规范》规定的洗手过程是什么？

**Reference answer:** 医务人员用流动水和洗手液（肥皂）揉搓冲洗双手，去除手部皮肤污垢、碎屑和部分微生物的过程。

**Evidence:**

- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `1942:1986` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 医务人员用流动水和洗手液（肥皂）揉搓冲洗双手，去除手部皮肤污垢、碎屑和部分微生物的过程。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0078 · single_fact

**Question:** 《医务人员手卫生规范》对医疗机构的手卫生制度和设施有哪些要求？

**Reference answer:** 医疗机构应制定并落实手卫生管理制度，配备有效、便捷、适宜的手卫生设施。

**Evidence:**

- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `2808:2843` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 医疗机构应制定并落实手卫生管理制度，配备有效、便捷、适宜的手卫生设施。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0079 · single_fact

**Question:** What is a Docker volume?

**Reference answer:** Volumes are persistent data stores for containers, created and managed by Docker.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `107:188` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes are persistent data stores for containers, created and managed by
Docker.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0080 · single_fact

**Question:** According to Docker Volumes, what does the guidance require of The subdirectory?

**Reference answer:** The subdirectory must exist in the volume before the volume is mounted to a container.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `5873:5959` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The subdirectory must exist in the volume before the volume is mounted to a container.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0081 · single_fact

**Question:** In Docker's volume example, can one container access another container's logs?

**Reference answer:** The containers can't access the other container's logs.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `14540:14595` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The containers can't access the other container's logs.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0082 · single_fact

**Question:** According to Docker Volumes, what does the document state about Volumes?

**Reference answer:** Volumes are useful for backups, restores, and migrations.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `21732:21789` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes are useful for backups, restores, and migrations.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0083 · single_fact

**Question:** According to Docker Volumes, what does the document state about The anonymous volumes?

**Reference answer:** The anonymous volumes are cleaned up when the container exits.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `23677:23739` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The anonymous volumes are cleaned up when the container exits.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0084 · single_fact

**Question:** According to Docker Volumes, what can A given volume do?

**Reference answer:** A given volume can be mounted into multiple containers simultaneously.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `2616:2686` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: A given volume can be mounted into multiple containers simultaneously.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0085 · single_fact

**Question:** According to Docker Volumes, what can New volumes do?

**Reference answer:** New volumes can have their content pre-populated by a container or build.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `1207:1280` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: New volumes can have their content pre-populated by a container or build.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0086 · single_fact

**Question:** According to Docker Volumes, what can Volumes do?

**Reference answer:** Volumes can be more safely shared among multiple containers.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `1146:1206` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes can be more safely shared among multiple containers.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0087 · single_fact

**Question:** How does MDN define a JavaScript Promise?

**Reference answer:** is an object representing the eventual completion or failure of an asynchronous operation.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `39:129` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: is an object representing the eventual completion or failure of an asynchronous operation.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0088 · single_fact

**Question:** What does the then() function return?

**Reference answer:** then() function returns a new promise , different from the original:

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `2008:2076` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: then()
function returns a
new promise
, different from the original:

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0089 · single_fact

**Question:** How does promise chaining order asynchronous operations?

**Reference answer:** A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `1221:1415` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0090 · single_fact

**Question:** According to MDN Using promises, what does the document state about Simple promise chains?

**Reference answer:** Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `9349:9458` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0091 · single_fact

**Question:** What is the stated purpose of the NIST Cybersecurity Framework?

**Reference answer:** Helping organizations to better understand and improve their management of cybersecurity risk

**Evidence:**

- [nist-csf](https://www.nist.gov/cyberframework) · extracted text `382:475` · SHA-256 `746cc27f2a2cfbda2374ace7bda15e3a356182e3f21aa7ea4911ad6c38291ae4`: Helping organizations to better understand and improve their management of cybersecurity risk

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0092 · single_fact

**Question:** Which kinds of organizations is NIST CSF 2.0 intended to help reduce cybersecurity risks?

**Reference answer:** For industry, government, and organizations to reduce cybersecurity risks

**Evidence:**

- [nist-csf](https://www.nist.gov/cyberframework) · extracted text `740:813` · SHA-256 `746cc27f2a2cfbda2374ace7bda15e3a356182e3f21aa7ea4911ad6c38291ae4`: For industry, government, and organizations to reduce cybersecurity risks

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0093 · single_fact

**Question:** What does a Kubernetes startup probe verify?

**Reference answer:** Startup probes verify whether the application within a container is started.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `649:725` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Startup probes verify whether the application within a container is started.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0094 · single_fact

**Question:** What does a Kubernetes readiness probe determine?

**Reference answer:** Readiness probes determine when a container is ready to accept traffic.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `2372:2443` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Readiness probes determine when a container is ready to accept traffic.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0095 · single_fact

**Question:** What does a Kubernetes liveness probe determine?

**Reference answer:** Liveness probes determine when to restart a container.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `1156:1210` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Liveness probes determine when to restart a container.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0096 · single_fact

**Question:** When does Kubernetes begin running liveness and readiness probes if a startup probe is configured?

**Reference answer:** If a startup probe is configured, Kubernetes does not execute liveness or readiness probes until the startup probe succeeds,

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `726:850` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: If a startup probe is configured, Kubernetes does not execute liveness or
readiness probes until the startup probe succeeds,

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0097 · single_fact

**Question:** According to Kubernetes Liveness, Readiness, and Startup Probes, what does the document state about The probe's success?

**Reference answer:** The probe's success is determined solely by the response status code, which is found in the response headers.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `16678:16787` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: The probe's success is determined solely by the response status code, which is found in the response headers.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0098 · single_fact

**Question:** According to Kubernetes Liveness, Readiness, and Startup Probes, what can Incorrect implementation of liveness probes do?

**Reference answer:** Incorrect implementation of liveness probes can lead to cascading failures.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `1991:2066` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Incorrect implementation of liveness probes can lead to cascading failures.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0099 · single_fact

**Question:** What is the basic purpose of git rebase?

**Reference answer:** Reapply commits on top of another base tip

**Evidence:**

- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `3166:3208` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: Reapply commits on top of another base tip

Split: `dev` · Review: `programmatic_candidate`

## PROF-0100 · single_fact

**Question:** What happens when git rebase encounters a merge conflict?

**Reference answer:** If there is a merge conflict during this process, git rebase will stop at the first problematic commit and leave conflict markers.

**Evidence:**

- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `4286:4416` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: If there is a merge conflict during this process,
git
rebase
will stop at the
first problematic commit and leave conflict markers.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0101 · single_fact

**Question:** What can interactive rebasing change about the commits being rebased?

**Reference answer:** Rebasing interactively means that you have a chance to edit the commits which are rebased. You can reorder the commits, and you can remove them (weeding out bad or otherwise unwanted patches).

**Evidence:**

- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `38312:38504` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: Rebasing interactively means that you have a chance to edit the commits
which are rebased. You can reorder the commits, and you can
remove them (weeding out bad or otherwise unwanted patches).

Split: `dev` · Review: `programmatic_candidate`

## PROF-0102 · single_fact

**Question:** What does the FTC advise businesses to control when storing personal data?

**Reference answer:** limit access to the places where personal data is stored or to control who can use particular databases.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `6795:6899` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: limit access to the places where personal data is stored or to control who can use particular databases.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0103 · single_fact

**Question:** Who should receive administrative access under the FTC security guidance?

**Reference answer:** Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `8793:8931` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0104 · single_fact

**Question:** According to FTC Start with Security, what does the guidance require of Businesses?

**Reference answer:** Businesses should consider other protections to help protect against password compromises – for example, multi-factor authentication or strong adaptive and salted hashing that has significant iterations of the hashing algorithm for each password.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `12058:12304` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Businesses should consider other protections to help protect against password compromises – for example, multi-factor authentication or strong adaptive and salted hashing that has significant iterations of the hashing algorithm for each password.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0105 · single_fact

**Question:** According to FTC Start with Security, what does the document state about Network security?

**Reference answer:** Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `34069:34233` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0106 · single_fact

**Question:** Where can medication errors occur, according to MedlinePlus?

**Reference answer:** Errors can happen in the hospital, at the health care provider's office, at the pharmacy, or at home.

**Evidence:**

- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `412:513` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: Errors can happen in the hospital, at the health care provider's office, at the pharmacy, or at home.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0107 · single_fact

**Question:** What information should a patient record in a medicine list?

**Reference answer:** Write down all of the medicines that you are taking, including the names of your medicines, how much you take, and when you take them.

**Evidence:**

- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `829:963` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: Write down all of the medicines that you are taking, including the names of your medicines, how much you take, and when you take them.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0108 · single_fact

**Question:** What should a patient ask when receiving a prescription?

**Reference answer:** When you get a prescription, ask the name of the medicine and check to make sure that the pharmacy gave you the right medicine.

**Evidence:**

- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `570:697` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: When you get a prescription, ask the name of the medicine and check to make sure that the pharmacy gave you the right medicine.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0109 · single_fact

**Question:** What does HTTP 200 (OK) indicate?

**Reference answer:** The 200 (OK) status code indicates that the request has succeeded.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `295264:295331` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The 200 (OK) status code indicates that the request has
 succeeded.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0110 · single_fact

**Question:** What does HTTP 403 (Forbidden) indicate?

**Reference answer:** The 403 (Forbidden) status code indicates that the server understood the request but refuses to fulfill it.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `325410:325518` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The 403 (Forbidden) status code indicates that the
 server understood the request but refuses to fulfill it.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0111 · single_fact

**Question:** What does HTTP 404 (Not Found) indicate?

**Reference answer:** The 404 (Not Found) status code indicates that the origin server did not find a current representation for the target resource or is not willing to disclose that one exists.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `326185:326360` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The 404 (Not Found) status code indicates that the origin
 server did not find a current representation for the
target resource
or is not willing to disclose that one
 exists.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0112 · single_fact

**Question:** What does HTTP 410 (Gone) indicate?

**Reference answer:** The 410 (Gone) status code indicates that access to the target resource is no longer available at the origin server and that this condition is likely to be permanent.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `329888:330055` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The 410 (Gone) status code indicates that access to the
target resource
is no longer available at the origin
 server and that this condition is likely to be permanent.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0113 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about HTTP header and trailer fields?

**Reference answer:** HTTP header and trailer fields are a widely used extension point for the protocol.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `351278:351360` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: HTTP header and trailer fields are a widely used extension point for the protocol.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0114 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The use of the Accept-Ranges field?

**Reference answer:** The use of the Accept-Ranges field is not restricted to origin servers.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `426199:426270` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The use of the Accept-Ranges field is not restricted to origin servers.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0115 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about Each message?

**Reference answer:** Each message is either a request or a response.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `7086:7133` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: Each message is either a request or a response.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0116 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about CONNECT?

**Reference answer:** CONNECT is intended for use in requests to a proxy.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `182114:182165` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: CONNECT is intended for use in requests to a proxy.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0117 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about HTTP intermediaries?

**Reference answer:** HTTP intermediaries are inherently situated for on-path attacks.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `367505:367569` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: HTTP intermediaries are inherently situated for on-path attacks.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0118 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The From header field?

**Reference answer:** The From header field is rarely sent by non-robotic user agents.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `193236:193300` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The From header field is rarely sent by non-robotic user agents.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0119 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The target of an HTTP request?

**Reference answer:** The target of an HTTP request is called a "resource".

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `17937:17990` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The target of an HTTP request is called a "resource".

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0120 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The Expect field value?

**Reference answer:** The Expect field value is case-insensitive.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `188421:188464` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The Expect field value is case-insensitive.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0121 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The 202 response?

**Reference answer:** The 202 response is intentionally noncommittal.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `298157:298204` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The 202 response is intentionally noncommittal.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0122 · single_fact

**Question:** Who can request registration of an HTTP field?

**Reference answer:** Any party can request registration of an HTTP field.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `349068:349120` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: Any party can request registration of an HTTP field.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0123 · single_fact

**Question:** Which HTTP request method is most likely to encounter conflicts?

**Reference answer:** Conflicts are most likely to occur in response to a PUT request.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `329391:329455` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: Conflicts are most likely to occur in response to a PUT request.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0124 · single_fact

**Question:** According to RFC 9110 HTTP Semantics, what does the document state about The Accept-Charset field?

**Reference answer:** The Accept-Charset field is now deprecated.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `425943:425986` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The Accept-Charset field is now deprecated.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0125 · single_fact

**Question:** React 文档如何定义组件实例的 State？

**Reference answer:** State 是屏幕上组件实例内部的状态。

**Evidence:**

- [react-state-zh](https://zh-hans.react.dev/learn/state-a-components-memory) · extracted text `12811:12831` · SHA-256 `e90f4b09daabca0c953bef603cd2192bf7f17ce8f79269847a6e645ba28bf1b2`: State 是屏幕上组件实例内部的状态。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0126 · single_fact

**Question:** 同时渲染同一 React 组件两次时，各副本的 State 是否共享？

**Reference answer:** 如果你渲染同一个组件两次，每个副本都会有完全隔离的 state

**Evidence:**

- [react-state-zh](https://zh-hans.react.dev/learn/state-a-components-memory) · extracted text `12837:12868` · SHA-256 `e90f4b09daabca0c953bef603cd2192bf7f17ce8f79269847a6e645ba28bf1b2`: 如果你渲染同一个组件两次，每个副本都会有完全隔离的 state

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0127 · single_fact

**Question:** Vue 计算属性如何跟踪依赖？

**Reference answer:** 计算属性会自动追踪响应式依赖。

**Evidence:**

- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2064:2079` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性会自动追踪响应式依赖。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0128 · single_fact

**Question:** Vue 的计算属性值在什么情况下重新计算？

**Reference answer:** 一个计算属性仅会在其响应式依赖更新时才重新计算。

**Evidence:**

- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2575:2599` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 一个计算属性仅会在其响应式依赖更新时才重新计算。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0129 · single_fact

**Question:** Vue 文档如何限定计算属性 getter 的职责？

**Reference answer:** 计算属性的 getter 应只做计算而没有任何其他的副作用

**Evidence:**

- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `5134:5163` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性的 getter 应只做计算而没有任何其他的副作用

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0130 · single_fact

**Question:** 根据《Kubernetes 存活、就绪和启动探针》，存活探针有哪些要求？

**Reference answer:** 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。

**Evidence:**

- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `667:704` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0131 · single_fact

**Question:** Kubernetes HTTP 探针依据响应中的什么信息判断成功？

**Reference answer:** 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

**Evidence:**

- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `7980:8011` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0132 · single_fact

**Question:** 根据《中华人民共和国食品安全法》，食品生产经营者有哪些要求？

**Reference answer:** 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `1049:1116` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0133 · single_fact

**Question:** 根据《中华人民共和国食品安全法》，从事食品生产、食品销售、餐饮服务有哪些要求？

**Reference answer:** 从事食品生产、食品销售、餐饮服务，应当依法取得许可。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `6685:6711` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 从事食品生产、食品销售、餐饮服务，应当依法取得许可。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0134 · single_fact

**Question:** 根据《中华人民共和国食品安全法》，专供婴幼儿和其他特定人群的主辅食品，其标签还有哪些要求？

**Reference answer:** 专供婴幼儿和其他特定人群的主辅食品，其标签还应当标明主要营养成分及其含量。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `12561:12598` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 专供婴幼儿和其他特定人群的主辅食品，其标签还应当标明主要营养成分及其含量。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0135 · single_fact

**Question:** 根据《中华人民共和国食品安全法》，发生食品安全事故需要启动应急预案的，县级以上人民政府有哪些要求？

**Reference answer:** 发生食品安全事故需要启动应急预案的，县级以上人民政府应当立即成立事故处置指挥机构，启动应急预案，依照前款和应急预案的规定进行处置。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `18689:18754` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 发生食品安全事故需要启动应急预案的，县级以上人民政府应当立即成立事故处置指挥机构，启动应急预案，依照前款和应急预案的规定进行处置。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0136 · single_fact

**Question:** 根据《中华人民共和国食品安全法》，因食品安全犯罪被判处有期徒刑以上刑罚的，终身有哪些禁止性规定？

**Reference answer:** 因食品安全犯罪被判处有期徒刑以上刑罚的，终身不得从事食品生产经营管理工作，也不得担任食品生产经营企业食品安全管理人员。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `26936:26995` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 因食品安全犯罪被判处有期徒刑以上刑罚的，终身不得从事食品生产经营管理工作，也不得担任食品生产经营企业食品安全管理人员。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0137 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第一百五十三条，国务院根据实际需要可以采取什么做法？

**Reference answer:** 第一百五十三条国务院根据实际需要，可以对食品安全监督管理体制作出调整。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `30864:30900` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第一百五十三条　国务院根据实际需要，可以对食品安全监督管理体制作出调整。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0138 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第八十九条，食品生产企业可以采取什么做法？

**Reference answer:** 第八十九条食品生产企业可以自行对所生产的食品进行检验，也可以委托符合本法规定的食品检验机构进行检验。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `15718:15769` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第八十九条　食品生产企业可以自行对所生产的食品进行检验，也可以委托符合本法规定的食品检验机构进行检验。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0139 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第五十一条，食品生产企业有哪些要求？

**Reference answer:** 第五十一条食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `9678:9792` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第五十一条　食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0140 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第一百二十条，任何单位和个人有哪些禁止性规定？

**Reference answer:** 第一百二十条任何单位和个人不得编造、散布虚假食品安全信息。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `21567:21597` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第一百二十条　任何单位和个人不得编造、散布虚假食品安全信息。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0141 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第二十二条，国务院食品安全监督管理部门有哪些要求？

**Reference answer:** 第二十二条国务院食品安全监督管理部门应当会同国务院有关部门，根据食品安全风险评估结果、食品安全监督管理信息，对食品安全状况进行综合分析。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `3911:3980` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第二十二条　国务院食品安全监督管理部门应当会同国务院有关部门，根据食品安全风险评估结果、食品安全监督管理信息，对食品安全状况进行综合分析。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0142 · single_fact

**Question:** 根据《中华人民共和国食品安全法》第八十条，特殊医学用途配方食品有哪些要求？

**Reference answer:** 第八十条特殊医学用途配方食品应当经国务院食品安全监督管理部门注册。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `14116:14150` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第八十条　特殊医学用途配方食品应当经国务院食品安全监督管理部门注册。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0143 · single_fact

**Question:** 根据《企业会计准则——基本准则》，财务会计报告使用者包括哪些内容？

**Reference answer:** 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `551:585` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0144 · single_fact

**Question:** 根据《企业会计准则——基本准则》，会计要素包括哪些内容？

**Reference answer:** 会计要素包括资产、负债、所有者权益、收入、费用和利润。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `785:812` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 会计要素包括资产、负债、所有者权益、收入、费用和利润。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0145 · single_fact

**Question:** 根据《企业会计准则——基本准则》第二十三条，负债指什么？

**Reference answer:** 第二十三条负债是指企业过去的交易或者事项形成的、预期会导致经济利益流出企业的现时义务。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1751:1794` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第二十三条负债是指企业过去的交易或者事项形成的、预期会导致经济利益流出企业的现时义务。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0146 · single_fact

**Question:** 根据《企业会计准则——基本准则》第三十三条，费用指什么？

**Reference answer:** 第三十三条费用是指企业在日常活动中发生的、会导致所有者权益减少的、与向所有者分配利润无关的经济利益的总流出。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `2492:2546` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第三十三条费用是指企业在日常活动中发生的、会导致所有者权益减少的、与向所有者分配利润无关的经济利益的总流出。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0147 · single_fact

**Question:** 根据《企业会计准则——基本准则》第四十四条，财务会计报告指什么？

**Reference answer:** 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3680:3741` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0148 · single_fact

**Question:** 根据《企业会计准则——基本准则》第四十七条，现金流量表指什么？

**Reference answer:** 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3900:3943` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0149 · single_fact

**Question:** 根据《企业会计准则——基本准则》第十七条，企业提供的会计信息有哪些要求？

**Reference answer:** 第十七条企业提供的会计信息应当反映与企业财务状况、经营成果和现金流量等有关的所有重要交易或者事项。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1225:1274` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第十七条企业提供的会计信息应当反映与企业财务状况、经营成果和现金流量等有关的所有重要交易或者事项。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0150 · single_fact

**Question:** 根据《企业会计准则——基本准则》，利润包括哪些内容？

**Reference answer:** 利润包括收入减去费用后的净额、直接计入当期利润的利得和损失等。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `2871:2902` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 利润包括收入减去费用后的净额、直接计入当期利润的利得和损失等。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0151 · single_fact

**Question:** 根据《企业会计准则——基本准则》，利得指什么？

**Reference answer:** 利得是指由企业非日常活动所形成的、会导致所有者权益增加的、与所有者投入资本无关的经济利益的流入。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `2185:2233` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 利得是指由企业非日常活动所形成的、会导致所有者权益增加的、与所有者投入资本无关的经济利益的流入。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0152 · single_fact

**Question:** 根据《企业会计准则——基本准则》，前款所指的企业过去的交易或者事项包括哪些内容？

**Reference answer:** 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1438:1476` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0153 · single_fact

**Question:** 根据《企业会计准则——基本准则》第二十六条，所有者权益指什么？

**Reference answer:** 第二十六条所有者权益是指企业资产扣除负债后由所有者享有的剩余权益。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `2017:2050` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第二十六条所有者权益是指企业资产扣除负债后由所有者享有的剩余权益。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0154 · single_fact

**Question:** 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？

**Reference answer:** 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0155 · single_fact

**Question:** 根据《中华人民共和国教师法》，不具备本法规定的教师资格学历的公民，申请获取教师资格有哪些要求？

**Reference answer:** 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `1856:1896` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0156 · single_fact

**Question:** 根据《中华人民共和国教师法》第十五条，各级师范学校毕业生有哪些要求？

**Reference answer:** 第十五条各级师范学校毕业生，应当按照国家有关规定从事教育教学工作。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2243:2277` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第十五条 各级师范学校毕业生，应当按照国家有关规定从事教育教学工作。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0157 · single_fact

**Question:** 根据《中华人民共和国教师法》第二十五条，教师的平均工资水平有哪些要求？

**Reference answer:** 第二十五条教师的平均工资水平应当不低于或者高于国家公务员的平均工资水平，并逐步提高。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2864:2907` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第二十五条 教师的平均工资水平应当不低于或者高于国家公务员的平均工资水平，并逐步提高。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0158 · single_fact

**Question:** 根据《中华人民共和国教师法》第三十一条，各级人民政府有哪些要求？

**Reference answer:** 第三十一条各级人民政府应当采取措施，改善国家补助、集体支付工资的中小学教师的待遇，逐步做到在工资收入上与国家支付工资的教师同工同酬，具体办法由地方各级人民政府根据本地区的实际情况规定。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3274:3367` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第三十一条 各级人民政府应当采取措施，改善国家补助、集体支付工资的中小学教师的待遇，逐步做到在工资收入上与国家支付工资的教师同工同酬，具体办法由地方各级人民政府根据本地区的实际情况规定。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0159 · single_fact

**Question:** 根据《中华人民共和国教师法》，县级以上地方人民政府可以采取什么做法？

**Reference answer:** 县级以上地方人民政府可以适当提高长期从事教育教学工作的中小学退休教师的退休金比例。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3232:3273` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 县级以上地方人民政府可以适当提高长期从事教育教学工作的中小学退休教师的退休金比例。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0160 · single_fact

**Question:** 根据《中华人民共和国教师法》第十九条，各级人民政府教育行政部门、学校主管部门和学校有哪些要求？

**Reference answer:** 第十九条各级人民政府教育行政部门、学校主管部门和学校应当制定教师培训规划，对教师进行多种形式的思想政治、业务培训。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2557:2615` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第十九条 各级人民政府教育行政部门、学校主管部门和学校应当制定教师培训规划，对教师进行多种形式的思想政治、业务培训。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0161 · single_fact

**Question:** 根据《中华人民共和国教师法》第二十二条，学校或者其他教育机构有哪些要求？

**Reference answer:** 第二十二条学校或者其他教育机构应当对教师的政治思想、业务水平、工作态度和工作成绩进行考核。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2714:2760` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第二十二条 学校或者其他教育机构应当对教师的政治思想、业务水平、工作态度和工作成绩进行考核。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0162 · single_fact

**Question:** 根据《中华人民共和国教师法》，县、乡两级人民政府有哪些要求？

**Reference answer:** 县、乡两级人民政府应当为农村中小学教师解决住房提供方便。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3095:3123` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 县、乡两级人民政府应当为农村中小学教师解决住房提供方便。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0163 · single_fact

**Question:** 根据《中华人民共和国教师法》，教师的聘任有哪些要求？

**Reference answer:** 教师的聘任应当遵循双方地位平等的原则，由学校和教师签订聘任合同，明确规定双方的权利、义务和责任。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2360:2408` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 教师的聘任应当遵循双方地位平等的原则，由学校和教师签订聘任合同，明确规定双方的权利、义务和责任。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0164 · single_fact

**Question:** 《2025年工业和信息化标准工作要点》提出制定多少项以上行业标准？

**Reference answer:** 制定行业标准1800 项以上

**Evidence:**

- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `351:366` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 制定行
业标准1800 项以上

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0165 · single_fact

**Question:** 《2025年工业和信息化标准工作要点》提出如何利用大模型赋能标准化建设？

**Reference answer:** 探索推进“人工智能+标准化”，利用人工智能大模型赋能标准化建设，推动人工智能技术在标准预研、编制、宣贯和实施推广等全生命周期的应用，提高标准制定效率，推动标准落地实施。

**Evidence:**

- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `1213:1306` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 探索推进“人工智能+标
准化”，利用人工智能大模型赋能标准化建设，推动人工智能


 2
技术在标准预研、编制、宣贯和实施推广等全生命周期的应

用，提高标准制定效率，推动标准落地实施。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0166 · single_fact

**Question:** 阿里云百炼的这份知识库 API 文档适用于哪类知识库？

**Reference answer:** 本文档仅适用于文档搜索类知识库。

**Evidence:**

- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `58:74` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 本文档仅适用于文档搜索类知识库。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0167 · single_fact

**Question:** 子账号通过阿里云 API 操作知识库之前需要具备什么权限和业务空间条件？

**Reference answer:** 子账号 （主账号不需要）需获取 API 权限 （AliyunBailianDataFullAccess 策略），并加入一个业务空间 ，然后才能通过阿里云 API 操作知识库。

**Evidence:**

- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `155:243` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 子账号
（主账号不需要）需获取
API
权限
（AliyunBailianDataFullAccess
策略），并
加入一个业务空间
，然后才能通过阿里云
API
操作知识库。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0168 · single_fact

**Question:** 阿里云百炼知识库功能分别支持中国站和国际站的哪些地域？

**Reference answer:** 知识库相关功能在中国站仅支持华北 2（北京） 地域，在国际站仅支持新加坡地域开通和使用，其他地域如德国（法兰克福）等均不支持知识库功能。

**Evidence:**

- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `78:149` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 知识库相关功能在中国站仅支持
华北
2（北京）
地域，在国际站仅支持
新加坡
地域开通和使用，其他地域如德国（法兰克福）等均不支持知识库功能。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0169 · single_fact

**Question:** 《个人信息保护法》如何定义个人信息？

**Reference answer:** 个人信息是以电子或者其他方式记录的与已识别或者可识别的自然人有关的各种信息，不包括匿名化处理后的信息。

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `530:585` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息是以电子或者其他方式记录的与已识别

或者可识别的自然人有关的各种信息，不包括匿名化处理后的信

息。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0170 · single_fact

**Question:** 《个人信息保护法》要求个人信息处理遵循哪些原则？

**Reference answer:** 处理个人信息应当遵循合法、正当、必要和诚信原则

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `636:661` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 处理个人信息应当遵循合法、正当、必要和诚信原

则

Split: `dev` · Review: `programmatic_candidate`

## PROF-0171 · single_fact

**Question:** 《个人信息保护法》列举了哪些个人信息处理活动？

**Reference answer:** 个人信息的处理包括个人信息的收集、存储、使用、加工、 传输、提供、公开、删除等。

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `588:629` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息的处理包括个人信息的收集、存储、使用、加工、

传输、提供、公开、删除等。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0172 · single_fact

**Question:** 根据《中华人民共和国个人信息保护法》，个人信息处理者有哪些要求？

**Reference answer:** 个人信息处理者应当提供便捷的撤回同意的方式。

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `1765:1787` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息处理者应当提供便捷的撤回同意的方式。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0173 · single_fact

**Question:** 根据《中华人民共和国安全生产法》，安全生产工作有哪些要求？

**Reference answer:** 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `989:1072` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0174 · single_fact

**Question:** 根据《中华人民共和国安全生产法》，生产经营单位可以采取什么做法？

**Reference answer:** 生产经营单位可以设置专职安全生产分管负责人，协助本单位主要负责人履行安全生产管理职责。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `4331:4374` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 生产经营单位可以设置专职安全生产分管负责人，协助本单位主要负责人履行安全生产管理职责。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0175 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第五十一条，生产经营单位有哪些要求？

**Reference answer:** 第五十一条生产经营单位必须依法参加工伤保险，为从业人员缴纳保险费。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `8325:8359` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第五十一条　生产经营单位必须依法参加工伤保险，为从业人员缴纳保险费。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0176 · single_fact

**Question:** 根据《中华人民共和国安全生产法》，负有安全生产监督管理职责的部门有哪些要求？

**Reference answer:** 负有安全生产监督管理职责的部门应当加强对生产经营单位行政处罚信息的及时归集、共享、应用和公开，对生产经营单位作出处罚决定后七个工作日内在监督管理部门公示系统予以公开曝光，强化对违法失信生产经营单位及其有关从业人员的社会监督，提高全社会安全生产诚信水平。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `12274:12400` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 负有安全生产监督管理职责的部门应当加强对生产经营单位行政处罚信息的及时归集、共享、应用和公开，对生产经营单位作出处罚决定后七个工作日内在监督管理部门公示系统予以公开曝光，强化对违法失信生产经营单位及其有关从业人员的社会监督，提高全社会安全生产诚信水平。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0177 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第八十九条，县级以上地方各级人民政府应急管理部门有哪些要求？

**Reference answer:** 第八十九条县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14033:14092` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十九条　县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0178 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第八十八条，任何单位和个人有哪些禁止性规定？

**Reference answer:** 第八十八条任何单位和个人不得阻挠和干涉对事故的依法调查处理。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14001:14032` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十八条　任何单位和个人不得阻挠和干涉对事故的依法调查处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0179 · single_fact

**Question:** 根据《中华人民共和国安全生产法》，生产经营单位有哪些禁止性规定？

**Reference answer:** 生产经营单位不得使用应当淘汰的危及生产安全的工艺、设备。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `6434:6462` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 生产经营单位不得使用应当淘汰的危及生产安全的工艺、设备。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0180 · single_fact

**Question:** 根据《中华人民共和国安全生产法》，监督检查有哪些禁止性规定？

**Reference answer:** 监督检查不得影响被检查单位的正常生产经营活动。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `10508:10531` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 监督检查不得影响被检查单位的正常生产经营活动。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0181 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第十三条，各级人民政府及其有关部门有哪些要求？

**Reference answer:** 第十三条各级人民政府及其有关部门应当采取多种形式，加强对有关安全生产的法律、法规和安全生产知识的宣传，增强全社会的安全生产意识。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `2760:2825` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第十三条　各级人民政府及其有关部门应当采取多种形式，加强对有关安全生产的法律、法规和安全生产知识的宣传，增强全社会的安全生产意识。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0182 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第三十条，生产经营单位的特种作业人员有哪些要求？

**Reference answer:** 第三十条生产经营单位的特种作业人员必须按照国家有关规定经专门的安全作业培训，取得相应资格，方可上岗作业。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `5341:5394` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第三十条　生产经营单位的特种作业人员必须按照国家有关规定经专门的安全作业培训，取得相应资格，方可上岗作业。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0183 · single_fact

**Question:** 根据《中华人民共和国安全生产法》第六十二条，县级以上地方各级人民政府有哪些要求？

**Reference answer:** 第六十二条县级以上地方各级人民政府应当根据本行政区域内的安全生产状况，组织有关部门按照职责分工，对本行政区域内容易发生重大生产安全事故的生产经营单位进行严格检查。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `9550:9632` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第六十二条　县级以上地方各级人民政府应当根据本行政区域内的安全生产状况，组织有关部门按照职责分工，对本行政区域内容易发生重大生产安全事故的生产经营单位进行严格检查。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0184 · single_fact

**Question:** 根据《中华人民共和国专利法》，发明指什么？

**Reference answer:** 发明，是指对产品、方法或者其改进所提出的新的技术方案。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `576:603` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 发明，是指对产品、方法或者其改进所提出的新的技术方案。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0185 · single_fact

**Question:** 根据《中华人民共和国专利法》，专利代理机构有哪些要求？

**Reference answer:** 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `2468:2547` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0186 · single_fact

**Question:** 根据《中华人民共和国专利法》第三十一条，一件发明或者实用新型专利申请有哪些要求？

**Reference answer:** 第三十一条一件发明或者实用新型专利申请应当限于一项发明或者实用新型。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `4657:4692` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第三十一条　一件发明或者实用新型专利申请应当限于一项发明或者实用新型。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0187 · single_fact

**Question:** 根据《中华人民共和国专利法》第四十八条，国务院专利行政部门、地方人民政府管理专利工作的部门有哪些要求？

**Reference answer:** 第四十八条国务院专利行政部门、地方人民政府管理专利工作的部门应当会同同级相关部门采取措施，加强专利公共服务，促进专利实施和运用。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `6631:6696` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第四十八条　国务院专利行政部门、地方人民政府管理专利工作的部门应当会同同级相关部门采取措施，加强专利公共服务，促进专利实施和运用。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0188 · single_fact

**Question:** 根据《中华人民共和国专利法》第七十条，国务院专利行政部门可以采取什么做法？

**Reference answer:** 第七十条国务院专利行政部门可以应专利权人或者利害关系人的请求处理在全国有重大影响的专利侵权纠纷。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `9467:9516` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第七十条　国务院专利行政部门可以应专利权人或者利害关系人的请求处理在全国有重大影响的专利侵权纠纷。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0189 · single_fact

**Question:** 根据《中华人民共和国专利法》第八十一条，向国务院专利行政部门申请专利和办理其他手续有哪些要求？

**Reference answer:** 第八十一条向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `11313:11352` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第八十一条　向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0190 · single_fact

**Question:** 根据《中华人民共和国专利法》，强制许可的理由消除并不再发生时，国务院专利行政部门有哪些要求？

**Reference answer:** 强制许可的理由消除并不再发生时，国务院专利行政部门应当根据专利权人的请求，经审查后作出终止实施强制许可的决定。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `8037:8092` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 强制许可的理由消除并不再发生时，国务院专利行政部门应当根据专利权人的请求，经审查后作出终止实施强制许可的决定。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0191 · single_fact

**Question:** 根据《中华人民共和国专利法》，授予专利权的外观设计有哪些禁止性规定？

**Reference answer:** 授予专利权的外观设计不得与他人在申请日以前已经取得的合法权利相冲突。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `3450:3484` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 授予专利权的外观设计不得与他人在申请日以前已经取得的合法权利相冲突。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0192 · single_fact

**Question:** 根据《中华人民共和国专利法》，转让专利申请权或者专利权的，当事人有哪些要求？

**Reference answer:** 转让专利申请权或者专利权的，当事人应当订立书面合同，并向国务院专利行政部门登记，由国务院专利行政部门予以公告。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `1521:1576` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 转让专利申请权或者专利权的，当事人应当订立书面合同，并向国务院专利行政部门登记，由国务院专利行政部门予以公告。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0193 · single_fact

**Question:** 根据《中华人民共和国专利法》，进行处理的管理专利工作的部门有哪些要求？

**Reference answer:** 进行处理的管理专利工作的部门应当事人的请求，可以就侵犯专利权的赔偿数额进行调解；调解不成的，当事人可以依照《中华人民共和国民事诉讼法》向人民法院起诉。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `8701:8776` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 进行处理的管理专利工作的部门应当事人的请求，可以就侵犯专利权的赔偿数额进行调解；调解不成的，当事人可以依照《中华人民共和国民事诉讼法》向人民法院起诉。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0194 · single_fact

**Question:** 根据《中华人民共和国专利法》，依赖遗传资源完成的发明创造，申请人有哪些要求？

**Reference answer:** 依赖遗传资源完成的发明创造，申请人应当在专利申请文件中说明该遗传资源的直接来源和原始来源；申请人无法说明原始来源的，应当陈述理由。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `4050:4115` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 依赖遗传资源完成的发明创造，申请人应当在专利申请文件中说明该遗传资源的直接来源和原始来源；申请人无法说明原始来源的，应当陈述理由。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0195 · single_fact

**Question:** Why is evaluating a model on the same data used for fitting methodologically wrong?

**Reference answer:** Learning the parameters of a prediction function and testing it on the same data is a methodological mistake: a model that would just repeat the labels of the samples that it has just seen would have a perfect score but would fail to predict anything useful on yet-unseen data.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `58:335` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Learning the parameters of a prediction function and testing it on the
same data is a methodological mistake: a model that would just repeat
the labels of the samples that it has just seen would have a perfect
score but would fail to predict anything useful on yet-unseen data.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0196 · single_fact

**Question:** How can scikit-learn quickly create a random training/test split?

**Reference answer:** In scikit-learn a random split into training and test sets can be quickly computed with the train_test_split helper function.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `845:970` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: In scikit-learn a random split into training and test sets
can be quickly computed with the
train_test_split
helper function.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0197 · single_fact

**Question:** What is the purpose of holding out a test set in supervised learning?

**Reference answer:** To avoid it, it is common practice when performing a (supervised) machine learning experiment to hold out part of the available data as a test set X_test, y_test

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `375:536` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: To avoid it, it is common practice when performing
a (supervised) machine learning experiment
to hold out part of the available data as a
test set
X_test,
y_test

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0198 · single_fact

**Question:** According to scikit-learn Cross-validation, what does the document state about Sorted groups?

**Reference answer:** Sorted groups are iterated over and assigned to folds.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `25159:25213` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Sorted groups are iterated over and assigned to folds.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0199 · single_fact

**Question:** What are the three stages of a pandas group-by operation?

**Reference answer:** By “group by” we are referring to a process involving one or more of the following steps: Splitting the data into groups based on some criteria. Applying a function to each group independently. Combining the results into a data structure.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `32:270` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: By “group by” we are referring to a process involving one or more of the following
steps:
Splitting
the data into groups based on some criteria.
Applying
a function to each group independently.
Combining
the results into a data structure.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0200 · single_fact

**Question:** According to pandas Group by, what does the document state about Many common aggregations?

**Reference answer:** Many common aggregations are built-in to GroupBy objects as methods.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `17782:17850` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Many common aggregations are built-in to GroupBy objects as methods.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0201 · single_fact

**Question:** According to pandas Group by, what does the document state about Named aggregation?

**Reference answer:** Named aggregation is also valid for Series groupby aggregations.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `29270:29334` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Named aggregation is also valid for Series groupby aggregations.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0202 · single_fact

**Question:** According to pandas Group by, what does the document state about A filtration?

**Reference answer:** A filtration is a GroupBy operation that subsets the original grouping object.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `42087:42165` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: A filtration is a GroupBy operation that subsets the original grouping object.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0203 · single_fact

**Question:** According to pandas Group by, what does the document state about The Series name?

**Reference answer:** The Series name is used as the name for the column index.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `66763:66820` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: The Series name is used as the name for the column index.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0204 · single_fact

**Question:** According to pandas Group by, what does the document state about Another common data transform?

**Reference answer:** Another common data transform is to replace missing data with the group mean.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `37214:37291` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Another common data transform is to replace missing data with the group mean.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0205 · single_fact

**Question:** According to pandas Group by, what does the document state about Another aggregation example?

**Reference answer:** Another aggregation example is to compute the number of unique values of each group.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `20466:20550` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Another aggregation example is to compute the number of unique values of each group.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0206 · single_fact

**Question:** According to pandas Group by, what does the document state about A common use of a transformation?

**Reference answer:** A common use of a transformation is to add the result back into the original DataFrame.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `31106:31193` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: A common use of a transformation is to add the result back into the original DataFrame.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0207 · single_fact

**Question:** What is logging used for in Python software?

**Reference answer:** Logging is a means of tracking events that happen when some software runs.

**Evidence:**

- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `359:433` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: Logging is a means of tracking events that happen when some software runs.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0208 · single_fact

**Question:** Which logger methods does the Python Logging HOWTO list for common severity levels?

**Reference answer:** debug() , info() , warning() , error() and critical()

**Evidence:**

- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `990:1043` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: debug()
,
info()
,
warning()
,
error()
and
critical()

Split: `dev` · Review: `programmatic_candidate`

## PROF-0209 · single_fact

**Question:** How does Python logging describe the importance assigned to an event?

**Reference answer:** Events also have an importance which the developer ascribes to the event; the importance can also be called the level or severity

**Evidence:**

- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `705:834` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: Events also have an importance which the
developer ascribes to the event; the importance can also be called the
level
or
severity

Split: `dev` · Review: `programmatic_candidate`

## PROF-0210 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，学校、教师有哪些要求？

**Reference answer:** 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `769:831` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0211 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，教育行政部门有哪些要求？

**Reference answer:** 教育行政部门应当支持、指导、监督学校及其教师依法依规实施教育惩戒。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `832:865` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 教育行政部门应当支持、指导、监督学校及其教师依法依规实施教育惩戒。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0212 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，学校可以采取什么做法？

**Reference answer:** 学校可以根据情况建立校规校纪执行委员会等组织机构，吸收教师、学生及家长、社会有关方面代表参加，负责确定可适用的教育惩戒措施，监督教育惩戒的实施，开展相关宣传教育等。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `1201:1283` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校可以根据情况建立校规校纪执行委员会等组织机构，吸收教师、学生及家长、社会有关方面代表参加，负责确定可适用的教育惩戒措施，监督教育惩戒的实施，开展相关宣传教育等。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0213 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，教师、学校对学生的违规物品可以采取什么做法？

**Reference answer:** 教师、学校对学生的违规物品可以予以暂扣并妥善保管，在适当时候交还学生家长；属于违法、危险物品的，应当及时报告公安机关、应急管理部门等有关部门依法处理。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `2352:2427` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 教师、学校对学生的违规物品可以予以暂扣并妥善保管，在适当时候交还学生家长；属于违法、危险物品的，应当及时报告公安机关、应急管理部门等有关部门依法处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0214 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，家长威胁、侮辱、伤害教师的，学校、教育行政部门有哪些要求？

**Reference answer:** 家长威胁、侮辱、伤害教师的，学校、教育行政部门应当依法保护教师人身安全、维护教师合法权益；情形严重的，应当及时向公安机关报告并配合公安机关、司法机关追究责任。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3308:3387` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 家长威胁、侮辱、伤害教师的，学校、教育行政部门应当依法保护教师人身安全、维护教师合法权益；情形严重的，应当及时向公安机关报告并配合公安机关、司法机关追究责任。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0215 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，各地可以采取什么做法？

**Reference answer:** 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3817:3850` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0216 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，教师因实施教育惩戒与学生及其家长发生纠纷，学校有哪些要求？

**Reference answer:** 教师因实施教育惩戒与学生及其家长发生纠纷，学校应当及时进行处理，教师无过错的，不得因教师实施教育惩戒而给予其处分或者其他不利处理。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `2970:3035` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 教师因实施教育惩戒与学生及其家长发生纠纷，学校应当及时进行处理，教师无过错的，不得因教师实施教育惩戒而给予其处分或者其他不利处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0217 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，学生申诉委员会有哪些要求？

**Reference answer:** 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3564:3618` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0218 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，对高中阶段学生，还可以采取什么做法？

**Reference answer:** 对高中阶段学生，还可以给予开除学籍的纪律处分。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `2119:2142` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 对高中阶段学生，还可以给予开除学籍的纪律处分。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0219 · single_fact

**Question:** 根据《中小学教育惩戒规则（试行）》，学校制定校规校纪有哪些要求？

**Reference answer:** 学校制定校规校纪，应当广泛征求教职工、学生和学生父母或者其他监护人（以下称家长）的意见；有条件的，可以组织有学生、家长及有关方面代表参加的听证。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `981:1053` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校制定校规校纪，应当广泛征求教职工、学生和学生父母或者其他监护人（以下称家长）的意见；有条件的，可以组织有学生、家长及有关方面代表参加的听证。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0220 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务经营者从事经营活动有哪些要求？

**Reference answer:** 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `619:734` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0221 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务经营者有哪些要求？

**Reference answer:** 电子商务经营者应当按照承诺或者与消费者约定的方式、时限向消费者交付商品或者服务，并承担商品运输中的风险和责任。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `2076:2131` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者应当按照承诺或者与消费者约定的方式、时限向消费者交付商品或者服务，并承担商品运输中的风险和责任。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0222 · single_fact

**Question:** 平台明知或应知商家侵害消费者权益却未采取必要措施时，依法承担什么责任？

**Reference answer:** 电子商务平台经营者知道或者应当知道平台内经营者销售的商品或者提供的服务不符合保障人身、财产安全的要求，或者有其他侵害消费者合法权益行为，未采取必要措施的，依法与该平台内经营者承担连带责任。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `4061:4155` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者知道或者应当知道平台内经营者销售的商品或者提供的服务不符合保障人身、财产安全的要求，或者有其他侵害消费者合法权益行为，未采取必要措施的，依法与该平台内经营者承担连带责任。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0223 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子支付服务提供者有哪些要求？

**Reference answer:** 电子支付服务提供者应当向用户免费提供对账服务以及最近三年的交易记录。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `6145:6179` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子支付服务提供者应当向用户免费提供对账服务以及最近三年的交易记录。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0224 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，跨境电子商务经营者可以采取什么做法？

**Reference answer:** 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7912:7945` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0225 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，国家进出口管理部门有哪些要求？

**Reference answer:** 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7823:7912` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0226 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务平台经营者为经营者之间的电子商务提供服务有哪些要求？

**Reference answer:** 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `5095:5175` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0227 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务平台经营者有哪些要求？

**Reference answer:** 电子商务平台经营者应当依照税收征收管理法律、行政法规的规定，向税务部门报送平台内经营者的身份信息和与纳税有关的信息，并应当提示依照本法第十条规定不需要办理市场主体登记的电子商务经营者依照本法第十一条第二款的规定办理税务登记。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `3016:3128` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者应当依照税收征收管理法律、行政法规的规定，向税务部门报送平台内经营者的身份信息和与纳税有关的信息，并应当提示依照本法第十条规定不需要办理市场主体登记的电子商务经营者依照本法第十一条第二款的规定办理税务登记。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0228 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务争议可以采取什么做法？

**Reference answer:** 电子商务争议可以通过协商和解，请求消费者组织、行业协会或者其他依法成立的调解组织调解，向有关部门投诉，提请仲裁，或者提起诉讼等方式解决。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `6914:6982` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务争议可以通过协商和解，请求消费者组织、行业协会或者其他依法成立的调解组织调解，向有关部门投诉，提请仲裁，或者提起诉讼等方式解决。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0229 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，电子商务经营者销售的商品或者提供的服务有哪些要求？

**Reference answer:** 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `1474:1544` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0230 · single_fact

**Question:** 根据《中华人民共和国电子商务法》，用户注销的，电子商务经营者有哪些要求？

**Reference answer:** 用户注销的，电子商务经营者应当立即删除该用户的信息；依照法律、行政法规的规定或者双方约定保存的，依照其规定。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `2517:2571` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 用户注销的，电子商务经营者应当立即删除该用户的信息；依照法律、行政法规的规定或者双方约定保存的，依照其规定。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0231 · single_fact

**Question:** What does access control enforce according to OWASP?

**Reference answer:** Access control enforces policy such that users cannot act outside of their intended permissions.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `780:876` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Access control enforces policy such that users cannot act outside of their intended permissions.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0232 · single_fact

**Question:** Where should access-control checks be implemented to be effective?

**Reference answer:** Access control is only effective when implemented in trusted server-side code or serverless APIs, where the attacker cannot modify the access control check or metadata.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2243:2411` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Access control is only effective when implemented in trusted server-side code or serverless APIs, where the attacker cannot modify the access control check or metadata.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0233 · single_fact

**Question:** When should stateful session identifiers be invalidated?

**Reference answer:** Stateful session identifiers should be invalidated on the server after logout.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `3134:3212` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Stateful session identifiers should be invalidated on the server after logout.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0234 · single_fact

**Question:** What should developers and QA staff include in tests for access control?

**Reference answer:** Developers and QA staff should include functional access control in their unit and integration tests.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `3504:3605` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Developers and QA staff should include functional access control in their unit and integration tests.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0235 · single_fact

**Question:** What default access-control policy does OWASP recommend for non-public resources?

**Reference answer:** Except for public resources, deny by default.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2412:2457` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Except for public resources, deny by default.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0236 · single_fact

**Question:** According to OWASP Broken Access Control, what does the document state about Admin rights?

**Reference answer:** Admin rights are required for access to the admin page.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `4112:4167` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Admin rights are required for access to the admin page.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0237 · single_fact

**Question:** According to OWASP Broken Access Control, what does CORS misconfiguration allow?

**Reference answer:** CORS misconfiguration allows API access from unauthorized or untrusted origins.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2023:2102` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: CORS misconfiguration allows API access from unauthorized or untrusted origins.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0238 · single_fact

**Question:** According to OWASP Broken Access Control, what does the guidance require of Model access controls?

**Reference answer:** Model access controls should enforce record ownership rather than allowing users to create, read, update, or delete any record.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2607:2734` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Model access controls should enforce record ownership rather than allowing users to create, read, update, or delete any record.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0239 · single_fact

**Question:** According to WHO Food safety, what does the document state about US$ 310 billion?

**Reference answer:** US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `212:320` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0240 · single_fact

**Question:** According to WHO Food safety, what does the document state about Norovirus?

**Reference answer:** Norovirus is a common cause of foodborne infections that is characterized by nausea, explosive vomiting, watery diarrhoea and abdominal pain.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `3686:3827` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Norovirus is a common cause of foodborne infections that is characterized by nausea, explosive vomiting, watery diarrhoea and abdominal pain.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0241 · single_fact

**Question:** According to WHO Food safety, what does the document state about Certain parasites?

**Reference answer:** Certain parasites are transmitted to humans exclusively through food, while for others, food represents a major pathway of infection.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `4397:4530` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Certain parasites are transmitted to humans exclusively through food, while for others, food represents a major pathway of infection.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0242 · single_fact

**Question:** According to WHO Food safety, what does the document state about Estimating the burden of foodborne disease?

**Reference answer:** Estimating the burden of foodborne disease is difficult due to the multiple sources of different hazards.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `8921:9026` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Estimating the burden of foodborne disease is difficult due to the multiple sources of different hazards.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0243 · single_fact

**Question:** According to WHO Food safety, what does the document state about Food safety?

**Reference answer:** Food safety is a shared responsibility among different national authorities and requires a multisectoral, One Health approach, to be addressed in all the steps of the food chain.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `11016:11194` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Food safety is a shared responsibility among different national authorities and requires a multisectoral, One Health approach, to be addressed in all the steps of the food chain.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0244 · single_fact

**Question:** According to WHO Food safety, what can Food producers do?

**Reference answer:** Food producers can safely grow fruits and vegetables using the WHO Five keys to growing safer fruits and vegetables.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `10899:11015` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Food producers can safely grow fruits and vegetables using the WHO Five keys to growing safer fruits and vegetables.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0245 · single_fact

**Question:** According to WHO Food safety, what does the document state about The sources of lead exposure?

**Reference answer:** The sources of lead exposure are varied, spanning from spices’ adulteration with lead chromate to preserve a certain colour, to the leaching of lead from recycled aluminium cookware, including staples (such as cereals or tubers) grown in contaminated soil.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `6725:6981` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: The sources of lead exposure are varied, spanning from spices’ adulteration with lead chromate to preserve a certain colour, to the leaching of lead from recycled aluminium cookware, including staples (such as cereals or tubers) grown in contaminated soil.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0246 · single_fact

**Question:** According to WHO Food safety, what can Chemical contamination do?

**Reference answer:** Chemical contamination can lead to acute poisoning or long-term diseases, such as cancer.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `1471:1560` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Chemical contamination can lead to acute poisoning or long-term diseases, such as cancer.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0247 · single_fact

**Question:** According to WHO Food safety, what does the guidance require of Governments?

**Reference answer:** Governments should prioritize food safety through development of evidence-based policies and risk-based, flexible regulatory frameworks and the establishment and implementation of effective food safety systems.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `10509:10719` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Governments should prioritize food safety through development of evidence-based policies and risk-based, flexible regulatory frameworks and the establishment and implementation of effective food safety systems.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0248 · single_fact

**Question:** According to WHO Food safety, what does the document state about Hepatitis E virus?

**Reference answer:** Hepatitis E virus is unique among the foodborne viruses in that it is a zoonotic pathogen with many asymptomatic animal reservoirs, notably swine.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `3996:4142` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Hepatitis E virus is unique among the foodborne viruses in that it is a zoonotic pathogen with many asymptomatic animal reservoirs, notably swine.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0249 · single_fact

**Question:** According to WHO Food safety, what does the document state about Foodborne illnesses?

**Reference answer:** Foodborne illnesses are usually infectious or toxic in nature and caused by bacteria, viruses, parasites or chemical substances entering the body through contaminated food.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `1298:1470` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Foodborne illnesses are usually infectious or toxic in nature and caused by bacteria, viruses, parasites or chemical substances entering the body through contaminated food.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0250 · single_fact

**Question:** According to WHO Food safety, what does the document state about Foodborne parasitic diseases?

**Reference answer:** Foodborne parasitic diseases are often neglected despite their significant impact on public health, including the potential for severe and sometimes fatal outcomes.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `4232:4396` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Foodborne parasitic diseases are often neglected despite their significant impact on public health, including the potential for severe and sometimes fatal outcomes.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0251 · single_fact

**Question:** According to WHO Food safety, what can Hepatitis A virus do?

**Reference answer:** Hepatitis A virus can also be transmitted by food and typically spreads through raw or undercooked seafood or contaminated raw fresh or frozen produce such as berries.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `3828:3995` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Hepatitis A virus can also be transmitted by food and typically spreads through raw or undercooked seafood or contaminated raw fresh or frozen produce such as berries.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0252 · single_fact

**Question:** According to WHO Food safety, what does the document state about Undercooked pig products?

**Reference answer:** Undercooked pig products are the main foods contaminated by hepatitis E virus.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `4143:4221` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Undercooked pig products are the main foods contaminated by hepatitis E virus.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0253 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《Vue 响应式基础》，和组件实例上的其他属性一样，方法也可以采取什么做法？
2. Vue 响应式对象与普通对象相比，属性访问和修改有什么区别？

**Reference answer:** 1. 和组件实例上的其他属性一样，方法也可以在模板上被访问。
2. 响应式对象是 JavaScript 代理 ，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `3964:3991` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 和组件实例上的其他属性一样，方法也可以在模板上被访问。
- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `5551:5629` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 响应式对象是
JavaScript 代理
，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0254 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？
2. 根据《中华人民共和国劳动合同法》，劳动行政部门的工作人员进行监督检查有哪些要求？

**Reference answer:** 1. 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
2. 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9609:9646` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0255 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国民法典》第八条，民事主体从事民事活动有哪些禁止性规定？
2. 根据《中华人民共和国民法典》第九百九十二条，人格权有哪些禁止性规定？

**Reference answer:** 1. 第八条民事主体从事民事活动，不得违反法律，不得违背公序良俗。
2. 第九百九十二条人格权不得放弃、转让或者继承。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `2488:2519` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第八条　民事主体从事民事活动，不得违反法律，不得违背公序良俗。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `94789:94812` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百九十二条　人格权不得放弃、转让或者继承。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0256 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. Vue 计算属性如何跟踪依赖？
2. Vue 文档如何限定计算属性 getter 的职责？

**Reference answer:** 1. 计算属性会自动追踪响应式依赖。
2. 计算属性的 getter 应只做计算而没有任何其他的副作用

**Evidence:**

- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2064:2079` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性会自动追踪响应式依赖。
- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `5134:5163` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性的 getter 应只做计算而没有任何其他的副作用

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0257 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《Kubernetes 存活、就绪和启动探针》，存活探针有哪些要求？
2. Kubernetes HTTP 探针依据响应中的什么信息判断成功？

**Reference answer:** 1. 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。
2. 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

**Evidence:**

- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `667:704` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。
- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `7980:8011` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0258 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，食品生产经营者有哪些要求？
2. 根据《中华人民共和国食品安全法》第一百五十三条，国务院根据实际需要可以采取什么做法？

**Reference answer:** 1. 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
2. 第一百五十三条国务院根据实际需要，可以对食品安全监督管理体制作出调整。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `1049:1116` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `30864:30900` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第一百五十三条　国务院根据实际需要，可以对食品安全监督管理体制作出调整。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0259 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，财务会计报告使用者包括哪些内容？
2. 根据《企业会计准则——基本准则》第四十七条，现金流量表指什么？

**Reference answer:** 1. 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
2. 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `551:585` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3900:3943` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0260 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？
2. 根据《中华人民共和国教师法》第三十一条，各级人民政府有哪些要求？

**Reference answer:** 1. 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
2. 第三十一条各级人民政府应当采取措施，改善国家补助、集体支付工资的中小学教师的待遇，逐步做到在工资收入上与国家支付工资的教师同工同酬，具体办法由地方各级人民政府根据本地区的实际情况规定。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3274:3367` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第三十一条 各级人民政府应当采取措施，改善国家补助、集体支付工资的中小学教师的待遇，逐步做到在工资收入上与国家支付工资的教师同工同酬，具体办法由地方各级人民政府根据本地区的实际情况规定。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0261 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《2025年工业和信息化标准工作要点》提出制定多少项以上行业标准？
2. 《2025年工业和信息化标准工作要点》提出如何利用大模型赋能标准化建设？

**Reference answer:** 1. 制定行业标准1800 项以上
2. 探索推进“人工智能+标准化”，利用人工智能大模型赋能标准化建设，推动人工智能技术在标准预研、编制、宣贯和实施推广等全生命周期的应用，提高标准制定效率，推动标准落地实施。

**Evidence:**

- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `351:366` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 制定行
业标准1800 项以上
- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `1213:1306` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 探索推进“人工智能+标
准化”，利用人工智能大模型赋能标准化建设，推动人工智能


 2
技术在标准预研、编制、宣贯和实施推广等全生命周期的应

用，提高标准制定效率，推动标准落地实施。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0262 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国安全生产法》，安全生产工作有哪些要求？
2. 根据《中华人民共和国安全生产法》第八十九条，县级以上地方各级人民政府应急管理部门有哪些要求？

**Reference answer:** 1. 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
2. 第八十九条县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `989:1072` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14033:14092` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十九条　县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0263 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，发明指什么？
2. 根据《中华人民共和国专利法》第八十一条，向国务院专利行政部门申请专利和办理其他手续有哪些要求？

**Reference answer:** 1. 发明，是指对产品、方法或者其改进所提出的新的技术方案。
2. 第八十一条向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `576:603` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 发明，是指对产品、方法或者其改进所提出的新的技术方案。
- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `11313:11352` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第八十一条　向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0264 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中小学教育惩戒规则（试行）》，学校、教师有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，各地可以采取什么做法？

**Reference answer:** 1. 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。
2. 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `769:831` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3817:3850` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0265 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国电子商务法》，电子商务经营者从事经营活动有哪些要求？
2. 根据《中华人民共和国电子商务法》，跨境电子商务经营者可以采取什么做法？

**Reference answer:** 1. 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。
2. 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `619:734` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7912:7945` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0266 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？
2. 根据《中华人民共和国劳动合同法》，非全日制用工小时计酬标准有哪些禁止性规定？

**Reference answer:** 1. 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
2. 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9060:9099` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0267 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国民法典》第八条，民事主体从事民事活动有哪些禁止性规定？
2. 根据《中华人民共和国民法典》第九百三十三条，委托人或者受托人可以采取什么做法？

**Reference answer:** 1. 第八条民事主体从事民事活动，不得违反法律，不得违背公序良俗。
2. 第九百三十三条委托人或者受托人可以随时解除委托合同。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `2488:2519` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第八条　民事主体从事民事活动，不得违反法律，不得违背公序良俗。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `88977:89004` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百三十三条　委托人或者受托人可以随时解除委托合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0268 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. Vue 的计算属性值在什么情况下重新计算？
2. Vue 文档如何限定计算属性 getter 的职责？

**Reference answer:** 1. 一个计算属性仅会在其响应式依赖更新时才重新计算。
2. 计算属性的 getter 应只做计算而没有任何其他的副作用

**Evidence:**

- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2575:2599` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 一个计算属性仅会在其响应式依赖更新时才重新计算。
- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `5134:5163` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性的 getter 应只做计算而没有任何其他的副作用

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0269 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》第二十二条，国务院食品安全监督管理部门有哪些要求？
2. 根据《中华人民共和国食品安全法》第一百五十三条，国务院根据实际需要可以采取什么做法？

**Reference answer:** 1. 第二十二条国务院食品安全监督管理部门应当会同国务院有关部门，根据食品安全风险评估结果、食品安全监督管理信息，对食品安全状况进行综合分析。
2. 第一百五十三条国务院根据实际需要，可以对食品安全监督管理体制作出调整。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `3911:3980` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第二十二条　国务院食品安全监督管理部门应当会同国务院有关部门，根据食品安全风险评估结果、食品安全监督管理信息，对食品安全状况进行综合分析。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `30864:30900` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第一百五十三条　国务院根据实际需要，可以对食品安全监督管理体制作出调整。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0270 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，财务会计报告使用者包括哪些内容？
2. 根据《企业会计准则——基本准则》第四十四条，财务会计报告指什么？

**Reference answer:** 1. 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
2. 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `551:585` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3680:3741` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0271 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？
2. 根据《中华人民共和国教师法》，县级以上地方人民政府可以采取什么做法？

**Reference answer:** 1. 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
2. 县级以上地方人民政府可以适当提高长期从事教育教学工作的中小学退休教师的退休金比例。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3232:3273` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 县级以上地方人民政府可以适当提高长期从事教育教学工作的中小学退休教师的退休金比例。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0272 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国安全生产法》，安全生产工作有哪些要求？
2. 根据《中华人民共和国安全生产法》第八十八条，任何单位和个人有哪些禁止性规定？

**Reference answer:** 1. 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
2. 第八十八条任何单位和个人不得阻挠和干涉对事故的依法调查处理。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `989:1072` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14001:14032` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十八条　任何单位和个人不得阻挠和干涉对事故的依法调查处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0273 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，转让专利申请权或者专利权的，当事人有哪些要求？
2. 根据《中华人民共和国专利法》第八十一条，向国务院专利行政部门申请专利和办理其他手续有哪些要求？

**Reference answer:** 1. 转让专利申请权或者专利权的，当事人应当订立书面合同，并向国务院专利行政部门登记，由国务院专利行政部门予以公告。
2. 第八十一条向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `1521:1576` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 转让专利申请权或者专利权的，当事人应当订立书面合同，并向国务院专利行政部门登记，由国务院专利行政部门予以公告。
- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `11313:11352` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第八十一条　向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0274 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中小学教育惩戒规则（试行）》，教育行政部门有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，各地可以采取什么做法？

**Reference answer:** 1. 教育行政部门应当支持、指导、监督学校及其教师依法依规实施教育惩戒。
2. 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `832:865` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 教育行政部门应当支持、指导、监督学校及其教师依法依规实施教育惩戒。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3817:3850` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0275 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国电子商务法》，电子商务经营者从事经营活动有哪些要求？
2. 根据《中华人民共和国电子商务法》，国家进出口管理部门有哪些要求？

**Reference answer:** 1. 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。
2. 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `619:734` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者从事经营活动，应当遵循自愿、平等、公平、诚信的原则，遵守法律和商业道德，公平参与市场竞争，履行消费者权益保护、环境保护、知识产权保护、网络安全与个人信息保护等方面的义务，承担产品和服务质量责任，接受政府和社会的监督。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7823:7912` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0276 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，固定期限劳动合同指什么？
2. 根据《中华人民共和国劳动合同法》，劳动行政部门的工作人员进行监督检查有哪些要求？

**Reference answer:** 1. 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。
2. 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `1522:1555` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9609:9646` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动行政部门的工作人员进行监督检查，应当出示证件，依法行使职权，文明执法。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0277 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国民法典》第一百六十一条，民事主体可以采取什么做法？
2. 根据《中华人民共和国民法典》第九百九十二条，人格权有哪些禁止性规定？

**Reference answer:** 1. 第一百六十一条民事主体可以通过代理人实施民事法律行为。
2. 第九百九十二条人格权不得放弃、转让或者继承。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `15842:15870` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第一百六十一条　民事主体可以通过代理人实施民事法律行为。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `94789:94812` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百九十二条　人格权不得放弃、转让或者继承。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0278 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，食品生产经营者有哪些要求？
2. 根据《中华人民共和国食品安全法》，因食品安全犯罪被判处有期徒刑以上刑罚的，终身有哪些禁止性规定？

**Reference answer:** 1. 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
2. 因食品安全犯罪被判处有期徒刑以上刑罚的，终身不得从事食品生产经营管理工作，也不得担任食品生产经营企业食品安全管理人员。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `1049:1116` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `26936:26995` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 因食品安全犯罪被判处有期徒刑以上刑罚的，终身不得从事食品生产经营管理工作，也不得担任食品生产经营企业食品安全管理人员。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0279 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，会计要素包括哪些内容？
2. 根据《企业会计准则——基本准则》第四十七条，现金流量表指什么？

**Reference answer:** 1. 会计要素包括资产、负债、所有者权益、收入、费用和利润。
2. 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `785:812` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 会计要素包括资产、负债、所有者权益、收入、费用和利润。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3900:3943` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十七条现金流量表是指反映企业在一定会计期间的现金和现金等价物流入和流出的会计报表。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0280 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？
2. 根据《中华人民共和国教师法》，县、乡两级人民政府有哪些要求？

**Reference answer:** 1. 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
2. 县、乡两级人民政府应当为农村中小学教师解决住房提供方便。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `3095:3123` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 县、乡两级人民政府应当为农村中小学教师解决住房提供方便。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0281 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国安全生产法》，安全生产工作有哪些要求？
2. 根据《中华人民共和国安全生产法》，负有安全生产监督管理职责的部门有哪些要求？

**Reference answer:** 1. 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
2. 负有安全生产监督管理职责的部门应当加强对生产经营单位行政处罚信息的及时归集、共享、应用和公开，对生产经营单位作出处罚决定后七个工作日内在监督管理部门公示系统予以公开曝光，强化对违法失信生产经营单位及其有关从业人员的社会监督，提高全社会安全生产诚信水平。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `989:1072` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 安全生产工作应当以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位，树牢安全发展理念，坚持安全第一、预防为主、综合治理的方针，从源头上防范化解重大安全风险。
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `12274:12400` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 负有安全生产监督管理职责的部门应当加强对生产经营单位行政处罚信息的及时归集、共享、应用和公开，对生产经营单位作出处罚决定后七个工作日内在监督管理部门公示系统予以公开曝光，强化对违法失信生产经营单位及其有关从业人员的社会监督，提高全社会安全生产诚信水平。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0282 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，发明指什么？
2. 根据《中华人民共和国专利法》第七十条，国务院专利行政部门可以采取什么做法？

**Reference answer:** 1. 发明，是指对产品、方法或者其改进所提出的新的技术方案。
2. 第七十条国务院专利行政部门可以应专利权人或者利害关系人的请求处理在全国有重大影响的专利侵权纠纷。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `576:603` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 发明，是指对产品、方法或者其改进所提出的新的技术方案。
- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `9467:9516` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第七十条　国务院专利行政部门可以应专利权人或者利害关系人的请求处理在全国有重大影响的专利侵权纠纷。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0283 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中小学教育惩戒规则（试行）》，学校制定校规校纪有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，各地可以采取什么做法？

**Reference answer:** 1. 学校制定校规校纪，应当广泛征求教职工、学生和学生父母或者其他监护人（以下称家长）的意见；有条件的，可以组织有学生、家长及有关方面代表参加的听证。
2. 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `981:1053` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校制定校规校纪，应当广泛征求教职工、学生和学生父母或者其他监护人（以下称家长）的意见；有条件的，可以组织有学生、家长及有关方面代表参加的听证。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3817:3850` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0284 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国电子商务法》，电子商务经营者销售的商品或者提供的服务有哪些要求？
2. 根据《中华人民共和国电子商务法》，跨境电子商务经营者可以采取什么做法？

**Reference answer:** 1. 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。
2. 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `1474:1544` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7912:7945` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 跨境电子商务经营者可以凭电子单证向国家进出口管理部门办理有关手续。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0285 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？
2. 根据《中华人民共和国劳动合同法》，用工单位有哪些禁止性规定？

**Reference answer:** 1. 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
2. 用工单位不得将被派遣劳动者再派遣到其他用人单位。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `8145:8169` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 用工单位不得将被派遣劳动者再派遣到其他用人单位。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0286 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国民法典》第一百六十一条，民事主体可以采取什么做法？
2. 根据《中华人民共和国民法典》第九百三十三条，委托人或者受托人可以采取什么做法？

**Reference answer:** 1. 第一百六十一条民事主体可以通过代理人实施民事法律行为。
2. 第九百三十三条委托人或者受托人可以随时解除委托合同。

**Evidence:**

- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `15842:15870` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第一百六十一条　民事主体可以通过代理人实施民事法律行为。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `88977:89004` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百三十三条　委托人或者受托人可以随时解除委托合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0287 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，从事食品生产、食品销售、餐饮服务有哪些要求？
2. 根据《中华人民共和国食品安全法》第一百五十三条，国务院根据实际需要可以采取什么做法？

**Reference answer:** 1. 从事食品生产、食品销售、餐饮服务，应当依法取得许可。
2. 第一百五十三条国务院根据实际需要，可以对食品安全监督管理体制作出调整。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `6685:6711` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 从事食品生产、食品销售、餐饮服务，应当依法取得许可。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `30864:30900` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第一百五十三条　国务院根据实际需要，可以对食品安全监督管理体制作出调整。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0288 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，会计要素包括哪些内容？
2. 根据《企业会计准则——基本准则》第四十四条，财务会计报告指什么？

**Reference answer:** 1. 会计要素包括资产、负债、所有者权益、收入、费用和利润。
2. 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `785:812` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 会计要素包括资产、负债、所有者权益、收入、费用和利润。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `3680:3741` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第四十四条财务会计报告是指企业对外提供的反映企业某一特定日期的财务状况和某一会计期间的经营成果、现金流量等会计信息的文件。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0289 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？
2. 根据《中华人民共和国教师法》第二十五条，教师的平均工资水平有哪些要求？

**Reference answer:** 1. 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
2. 第二十五条教师的平均工资水平应当不低于或者高于国家公务员的平均工资水平，并逐步提高。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2864:2907` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第二十五条 教师的平均工资水平应当不低于或者高于国家公务员的平均工资水平，并逐步提高。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0290 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国安全生产法》第十三条，各级人民政府及其有关部门有哪些要求？
2. 根据《中华人民共和国安全生产法》第八十九条，县级以上地方各级人民政府应急管理部门有哪些要求？

**Reference answer:** 1. 第十三条各级人民政府及其有关部门应当采取多种形式，加强对有关安全生产的法律、法规和安全生产知识的宣传，增强全社会的安全生产意识。
2. 第八十九条县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

**Evidence:**

- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `2760:2825` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第十三条　各级人民政府及其有关部门应当采取多种形式，加强对有关安全生产的法律、法规和安全生产知识的宣传，增强全社会的安全生产意识。
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14033:14092` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十九条　县级以上地方各级人民政府应急管理部门应当定期统计分析本行政区域内发生生产安全事故的情况，并定期向社会公布。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0291 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，专利代理机构有哪些要求？
2. 根据《中华人民共和国专利法》第八十一条，向国务院专利行政部门申请专利和办理其他手续有哪些要求？

**Reference answer:** 1. 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。
2. 第八十一条向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `2468:2547` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。
- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `11313:11352` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 第八十一条　向国务院专利行政部门申请专利和办理其他手续，应当按照规定缴纳费用。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0292 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中小学教育惩戒规则（试行）》，学校、教师有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，学生申诉委员会有哪些要求？

**Reference answer:** 1. 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。
2. 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

**Evidence:**

- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `769:831` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学校、教师应当遵循教育规律，依法履行职责，通过积极管教和教育惩戒的实施，及时纠正学生错误言行，培养学生的规则意识、责任意识。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3564:3618` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0293 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国电子商务法》，电子商务经营者销售的商品或者提供的服务有哪些要求？
2. 根据《中华人民共和国电子商务法》，国家进出口管理部门有哪些要求？

**Reference answer:** 1. 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。
2. 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

**Evidence:**

- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `1474:1544` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务经营者销售的商品或者提供的服务应当符合保障人身、财产安全的要求和环境保护要求，不得销售或者提供法律、行政法规禁止交易的商品或者服务。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7823:7912` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0294 · long_span_single_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，固定期限劳动合同指什么？
2. 根据《中华人民共和国劳动合同法》，非全日制用工小时计酬标准有哪些禁止性规定？

**Reference answer:** 1. 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。
2. 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `1522:1555` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 固定期限劳动合同，是指用人单位与劳动者约定合同终止时间的劳动合同。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `9060:9099` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 非全日制用工小时计酬标准不得低于用人单位所在地人民政府规定的最低小时工资标准。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0295 · long_span_single_source

**Question:** Answer each question and cite its source:
1. Does merely calling an asyncio coroutine schedule it to run?
2. According to Python asyncio Tasks, what does the document state about Tasks?

**Reference answer:** 1. Note that simply calling a coroutine will not schedule it to be executed:
2. Tasks are used to run coroutines in event loops.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `745:818` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Note that simply calling a coroutine will not schedule it to
be executed:
- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `32015:32063` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks are used to run coroutines in event loops.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0296 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What do React Effects let a component synchronize with?
2. According to React, what causes a buying action?

**Reference answer:** 1. let you run some code after rendering so that you can synchronize your component with some system outside of React.
2. Buying is not caused by rendering; it’s caused by a specific interaction.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `316:431` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: let you run some code after rendering so that you can synchronize your component with some system outside of React.
- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `30783:30856` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Buying is not caused by rendering; it’s caused by a specific interaction.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0297 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How many transaction isolation levels does the SQL standard define?
2. According to PostgreSQL Transaction Isolation, what does the document state about The Serializable isolation level?

**Reference answer:** 1. standard defines four levels of transaction isolation.
2. The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `576:630` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: standard defines four levels of transaction isolation.
- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `23422:23642` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0298 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does LangChain define an agent?
2. According to LangChain Agents, what does the document state about Agents?

**Reference answer:** 1. An agent is a model calling tools in a loop until a given task is complete.
2. Agents are especially useful when they can take action rather than just generate text.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `0:75` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: An agent is a model calling tools in a loop until a given task is complete.
- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `24302:24388` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Agents are especially useful when they can take action rather than just generate text.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0299 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does WHO define patient safety?
2. According to WHO Patient safety, what can Failure to correctly identify patients do?

**Reference answer:** 1. Patient safety is defined as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."
2. Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `343:514` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Patient safety is
defined
as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `3815:3940` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0300 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What is the general WCAG requirement for non-text content presented to users?
2. According to WCAG 2.2 Non-text Content, what does the document state about An image of a chart?

**Reference answer:** 1. non-text content that is presented to the user has a text alternative that serves the equivalent purpose
2. An image of a chart is described in text in the paragraph after the chart.

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `292:396` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: non-text content
that is presented to the user has a
text alternative
that serves the equivalent purpose
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `28875:28949` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: An image of a chart is described in text in the paragraph after the chart.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0301 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to SEC Introduction to Investing, what does the document state about A savings account?
2. According to SEC Introduction to Investing, what does the document state about Funds for short-term goals?

**Reference answer:** 1. A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.
2. Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `602:722` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.
- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `8041:8191` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0302 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What is a Docker volume?
2. According to Docker Volumes, what does the document state about The anonymous volumes?

**Reference answer:** 1. Volumes are persistent data stores for containers, created and managed by Docker.
2. The anonymous volumes are cleaned up when the container exits.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `107:188` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes are persistent data stores for containers, created and managed by
Docker.
- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `23677:23739` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The anonymous volumes are cleaned up when the container exits.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0303 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does MDN define a JavaScript Promise?
2. According to MDN Using promises, what does the document state about Simple promise chains?

**Reference answer:** 1. is an object representing the eventual completion or failure of an asynchronous operation.
2. Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `39:129` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: is an object representing the eventual completion or failure of an asynchronous operation.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `9349:9458` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0304 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What does a Kubernetes startup probe verify?
2. According to Kubernetes Liveness, Readiness, and Startup Probes, what does the document state about The probe's success?

**Reference answer:** 1. Startup probes verify whether the application within a container is started.
2. The probe's success is determined solely by the response status code, which is found in the response headers.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `649:725` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Startup probes verify whether the application within a container is started.
- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `16678:16787` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: The probe's success is determined solely by the response status code, which is found in the response headers.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0305 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What is the basic purpose of git rebase?
2. What can interactive rebasing change about the commits being rebased?

**Reference answer:** 1. Reapply commits on top of another base tip
2. Rebasing interactively means that you have a chance to edit the commits which are rebased. You can reorder the commits, and you can remove them (weeding out bad or otherwise unwanted patches).

**Evidence:**

- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `3166:3208` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: Reapply commits on top of another base tip
- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `38312:38504` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: Rebasing interactively means that you have a chance to edit the commits
which are rebased. You can reorder the commits, and you can
remove them (weeding out bad or otherwise unwanted patches).

Split: `dev` · Review: `programmatic_candidate`

## PROF-0306 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What does the FTC advise businesses to control when storing personal data?
2. According to FTC Start with Security, what does the document state about Network security?

**Reference answer:** 1. limit access to the places where personal data is stored or to control who can use particular databases.
2. Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `6795:6899` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: limit access to the places where personal data is stored or to control who can use particular databases.
- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `34069:34233` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0307 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to RFC 9110 HTTP Semantics, what does the document state about Each message?
2. According to RFC 9110 HTTP Semantics, what does the document state about The use of the Accept-Ranges field?

**Reference answer:** 1. Each message is either a request or a response.
2. The use of the Accept-Ranges field is not restricted to origin servers.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `7086:7133` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: Each message is either a request or a response.
- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `426199:426270` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The use of the Accept-Ranges field is not restricted to origin servers.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0308 · long_span_single_source

**Question:** Answer each question and cite its source:
1. Why is evaluating a model on the same data used for fitting methodologically wrong?
2. According to scikit-learn Cross-validation, what does the document state about Sorted groups?

**Reference answer:** 1. Learning the parameters of a prediction function and testing it on the same data is a methodological mistake: a model that would just repeat the labels of the samples that it has just seen would have a perfect score but would fail to predict anything useful on yet-unseen data.
2. Sorted groups are iterated over and assigned to folds.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `58:335` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Learning the parameters of a prediction function and testing it on the
same data is a methodological mistake: a model that would just repeat
the labels of the samples that it has just seen would have a perfect
score but would fail to predict anything useful on yet-unseen data.
- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `25159:25213` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Sorted groups are iterated over and assigned to folds.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0309 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What are the three stages of a pandas group-by operation?
2. According to pandas Group by, what does the document state about The Series name?

**Reference answer:** 1. By “group by” we are referring to a process involving one or more of the following steps: Splitting the data into groups based on some criteria. Applying a function to each group independently. Combining the results into a data structure.
2. The Series name is used as the name for the column index.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `32:270` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: By “group by” we are referring to a process involving one or more of the following
steps:
Splitting
the data into groups based on some criteria.
Applying
a function to each group independently.
Combining
the results into a data structure.
- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `66763:66820` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: The Series name is used as the name for the column index.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0310 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What does access control enforce according to OWASP?
2. According to OWASP Broken Access Control, what does the document state about Admin rights?

**Reference answer:** 1. Access control enforces policy such that users cannot act outside of their intended permissions.
2. Admin rights are required for access to the admin page.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `780:876` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Access control enforces policy such that users cannot act outside of their intended permissions.
- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `4112:4167` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Admin rights are required for access to the admin page.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0311 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to WHO Food safety, what does the document state about US$ 310 billion?
2. According to WHO Food safety, what does the document state about Food safety?

**Reference answer:** 1. US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
2. Food safety is a shared responsibility among different national authorities and requires a multisectoral, One Health approach, to be addressed in all the steps of the food chain.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `212:320` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `11016:11194` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Food safety is a shared responsibility among different national authorities and requires a multisectoral, One Health approach, to be addressed in all the steps of the food chain.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0312 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to Python asyncio Tasks, what can Tasks do?
2. According to Python asyncio Tasks, what does the document state about Tasks?

**Reference answer:** 1. Tasks can easily and safely be cancelled.
2. Tasks are used to run coroutines in event loops.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `7115:7156` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks can easily and safely be cancelled.
- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `32015:32063` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks are used to run coroutines in event loops.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0313 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to React Synchronizing with Effects, what does the document state about Connecting to a server?
2. According to React, what causes a buying action?

**Reference answer:** 1. Connecting to a server is not a pure calculation (it’s a side effect) so it can’t happen during rendering.
2. Buying is not caused by rendering; it’s caused by a specific interaction.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `1677:1783` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Connecting to a server is not a pure calculation (it’s a side effect) so it can’t happen during rendering.
- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `30783:30856` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Buying is not caused by rendering; it’s caused by a specific interaction.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0314 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What outcome does Serializable isolation guarantee for concurrent transactions?
2. According to PostgreSQL Transaction Isolation, what does the document state about The Serializable isolation level?

**Reference answer:** 1. The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.
2. The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `631:876` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.
- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `23422:23642` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0315 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What components make up an agent harness in this LangChain guide?
2. According to LangChain Agents, what does the document state about Agents?

**Reference answer:** 1. A harness is everything around that loop: the prompt, the tools, and any middleware that shapes the model’s behavior.
2. Agents are especially useful when they can take action rather than just generate text.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `76:193` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: A harness is everything around that loop: the prompt, the tools, and any middleware that shapes the model’s behavior.
- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `24302:24388` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Agents are especially useful when they can take action rather than just generate text.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0316 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What are the reported consequences of health care-associated infections?
2. According to WHO Patient safety, what can Failure to correctly identify patients do?

**Reference answer:** 1. health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths
2. Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1583:1816` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `3815:3940` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0317 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What alternatives does WCAG require for CAPTCHA that uses non-text content?
2. According to WCAG 2.2 Non-text Content, what does the document state about An image of a chart?

**Reference answer:** 1. If the purpose of non-text content is to confirm that content is being accessed by a person rather than a computer, then text alternatives that identify and describe the purpose of the non-text content are provided, and alternative forms of CAPTCHA using output modes for different types of sensory perception are provided
2. An image of a chart is described in text in the paragraph after the chart.

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `1263:1588` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: If the purpose of non-text content is to confirm that content is being accessed by
 a person rather than a computer, then text alternatives that identify and describe
 the purpose of the non-text content are provided, and alternative forms of CAPTCHA
 using output modes for different types of sensory perception are provided
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `28875:28949` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: An image of a chart is described in text in the paragraph after the chart.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0318 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to SEC Introduction to Investing, what does the document state about Regular investing?
2. According to SEC Introduction to Investing, what does the document state about Funds for short-term goals?

**Reference answer:** 1. Regular investing means that you put a set dollar amount or a set percentage of your income into your investment accounts.
2. Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `2574:2696` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Regular investing means that you put a set dollar amount or a set percentage of your income into your investment accounts.
- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `8041:8191` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Funds for short-term goals are generally held in an account that allows you to access the funds quickly without any tax penalties or significant fees.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0319 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to Docker Volumes, what can Volumes do?
2. According to Docker Volumes, what does the document state about The anonymous volumes?

**Reference answer:** 1. Volumes can be more safely shared among multiple containers.
2. The anonymous volumes are cleaned up when the container exits.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `1146:1206` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes can be more safely shared among multiple containers.
- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `23677:23739` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The anonymous volumes are cleaned up when the container exits.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0320 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does promise chaining order asynchronous operations?
2. According to MDN Using promises, what does the document state about Simple promise chains?

**Reference answer:** 1. A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.
2. Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `1221:1415` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `9349:9458` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0321 · long_span_single_source

**Question:** Answer each question and cite its source:
1. When does Kubernetes begin running liveness and readiness probes if a startup probe is configured?
2. According to Kubernetes Liveness, Readiness, and Startup Probes, what does the document state about The probe's success?

**Reference answer:** 1. If a startup probe is configured, Kubernetes does not execute liveness or readiness probes until the startup probe succeeds,
2. The probe's success is determined solely by the response status code, which is found in the response headers.

**Evidence:**

- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `726:850` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: If a startup probe is configured, Kubernetes does not execute liveness or
readiness probes until the startup probe succeeds,
- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `16678:16787` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: The probe's success is determined solely by the response status code, which is found in the response headers.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0322 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What happens when git rebase encounters a merge conflict?
2. What can interactive rebasing change about the commits being rebased?

**Reference answer:** 1. If there is a merge conflict during this process, git rebase will stop at the first problematic commit and leave conflict markers.
2. Rebasing interactively means that you have a chance to edit the commits which are rebased. You can reorder the commits, and you can remove them (weeding out bad or otherwise unwanted patches).

**Evidence:**

- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `4286:4416` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: If there is a merge conflict during this process,
git
rebase
will stop at the
first problematic commit and leave conflict markers.
- [git-rebase](https://git-scm.com/docs/git-rebase) · extracted text `38312:38504` · SHA-256 `9575b84a79faf35f390cf7674be07fc7dd799d796152829f23eb4233ad47ef95`: Rebasing interactively means that you have a chance to edit the commits
which are rebased. You can reorder the commits, and you can
remove them (weeding out bad or otherwise unwanted patches).

Split: `dev` · Review: `programmatic_candidate`

## PROF-0323 · long_span_single_source

**Question:** Answer each question and cite its source:
1. Who should receive administrative access under the FTC security guidance?
2. According to FTC Start with Security, what does the document state about Network security?

**Reference answer:** 1. Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.
2. Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `8793:8931` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.
- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `34069:34233` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0324 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to RFC 9110 HTTP Semantics, what does the document state about Each message?
2. According to RFC 9110 HTTP Semantics, what does the document state about The Accept-Charset field?

**Reference answer:** 1. Each message is either a request or a response.
2. The Accept-Charset field is now deprecated.

**Evidence:**

- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `7086:7133` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: Each message is either a request or a response.
- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `425943:425986` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The Accept-Charset field is now deprecated.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0325 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What is the purpose of holding out a test set in supervised learning?
2. According to scikit-learn Cross-validation, what does the document state about Sorted groups?

**Reference answer:** 1. To avoid it, it is common practice when performing a (supervised) machine learning experiment to hold out part of the available data as a test set X_test, y_test
2. Sorted groups are iterated over and assigned to folds.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `375:536` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: To avoid it, it is common practice when performing
a (supervised) machine learning experiment
to hold out part of the available data as a
test set
X_test,
y_test
- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `25159:25213` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Sorted groups are iterated over and assigned to folds.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0326 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to pandas Group by, what does the document state about Many common aggregations?
2. According to pandas Group by, what does the document state about The Series name?

**Reference answer:** 1. Many common aggregations are built-in to GroupBy objects as methods.
2. The Series name is used as the name for the column index.

**Evidence:**

- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `17782:17850` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Many common aggregations are built-in to GroupBy objects as methods.
- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `66763:66820` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: The Series name is used as the name for the column index.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0327 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What does access control enforce according to OWASP?
2. What should developers and QA staff include in tests for access control?

**Reference answer:** 1. Access control enforces policy such that users cannot act outside of their intended permissions.
2. Developers and QA staff should include functional access control in their unit and integration tests.

**Evidence:**

- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `780:876` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Access control enforces policy such that users cannot act outside of their intended permissions.
- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `3504:3605` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Developers and QA staff should include functional access control in their unit and integration tests.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0328 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to WHO Food safety, what does the document state about US$ 310 billion?
2. According to WHO Food safety, what can Food producers do?

**Reference answer:** 1. US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
2. Food producers can safely grow fruits and vegetables using the WHO Five keys to growing safer fruits and vegetables.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `212:320` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `10899:11015` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Food producers can safely grow fruits and vegetables using the WHO Five keys to growing safer fruits and vegetables.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0329 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What exception is raised when an asyncio task is cancelled?
2. According to Python asyncio Tasks, what does the document state about Tasks?

**Reference answer:** 1. When a task is cancelled, asyncio.CancelledError will be raised in the task at the next opportunity.
2. Tasks are used to run coroutines in event loops.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `7157:7257` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: When a task is cancelled,
asyncio.CancelledError
will be raised
in the task at the next opportunity.
- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `32015:32063` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks are used to run coroutines in event loops.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0330 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to React Synchronizing with Effects, what does the document state about Synchronizing with an external system?
2. According to React, what causes a buying action?

**Reference answer:** 1. Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
2. Buying is not caused by rendering; it’s caused by a specific interaction.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `9458:9576` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `30783:30856` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Buying is not caused by rendering; it’s caused by a specific interaction.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0331 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does the SQL standard define the three isolation levels below Serializable?
2. According to PostgreSQL Transaction Isolation, what does the document state about The Serializable isolation level?

**Reference answer:** 1. The other three levels are defined in terms of phenomena, resulting from interaction between concurrent transactions, which must not occur at each level.
2. The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `877:1030` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The other three levels are defined in terms of phenomena, resulting from interaction between concurrent transactions, which must not occur at each level.
- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `23422:23642` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The Serializable isolation level is implemented using a technique known in academic database literature as Serializable Snapshot Isolation, which builds on Snapshot Isolation by adding checks for serialization anomalies.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0332 · long_span_single_source

**Question:** Answer each question and cite its source:
1. How does LangChain define an agent?
2. According to LangChain Agents, what does the document state about Common patterns?

**Reference answer:** 1. An agent is a model calling tools in a loop until a given task is complete.
2. Common patterns are prebuilt as first-class middleware.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `0:75` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: An agent is a model calling tools in a loop until a given task is complete.
- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `23471:23526` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Common patterns are prebuilt as first-class middleware.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0333 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to WCAG 2.2 Non-text Content, what does the guidance require of Text alternatives and equivalents?
2. According to WCAG 2.2 Non-text Content, what does the document state about An image of a chart?

**Reference answer:** 1. Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).
2. An image of a chart is described in text in the paragraph after the chart.

**Evidence:**

- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `4262:4402` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `28875:28949` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: An image of a chart is described in text in the paragraph after the chart.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0334 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to SEC Introduction to Investing, what does the document state about A savings account?
2. According to SEC Introduction to Investing, what can Diversification  do?

**Reference answer:** 1. A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.
2. Diversification can help reduce your losses if the market drops, because when different sectors may be down, other sectors may rally and allow a diversified investor to break even or even post gains.

**Evidence:**

- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `602:722` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: A savings account is a good choice for short-term goals or to hold an emergency fund that can cover unexpected expenses.
- [investor-gov-introduction](https://www.investor.gov/introduction-investing) · extracted text `5425:5624` · SHA-256 `324539fea832a1933c49bffad002f6dd8a176875af52703ca1310e70a0d5e877`: Diversification can help reduce your losses if the market drops, because when different sectors may be down, other sectors may rally and allow a diversified investor to break even or even post gains.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0335 · long_span_single_source

**Question:** Answer each question and cite its source:
1. According to Docker Volumes, what can New volumes do?
2. According to Docker Volumes, what does the document state about The anonymous volumes?

**Reference answer:** 1. New volumes can have their content pre-populated by a container or build.
2. The anonymous volumes are cleaned up when the container exits.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `1207:1280` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: New volumes can have their content pre-populated by a container or build.
- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `23677:23739` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The anonymous volumes are cleaned up when the container exits.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0336 · long_span_single_source

**Question:** Answer each question and cite its source:
1. What does the then() function return?
2. According to MDN Using promises, what does the document state about Simple promise chains?

**Reference answer:** 1. then() function returns a new promise , different from the original:
2. Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

**Evidence:**

- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `2008:2076` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: then()
function returns a
new promise
, different from the original:
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `9349:9458` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0337 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. Does merely calling an asyncio coroutine schedule it to run?
2. According to Python asyncio Tasks, what can Timeout context managers do?
3. Which logger methods does the Python Logging HOWTO list for common severity levels?

**Reference answer:** 1. Note that simply calling a coroutine will not schedule it to be executed:
2. Timeout context managers can be safely nested.
3. debug() , info() , warning() , error() and critical()

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `745:818` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Note that simply calling a coroutine will not schedule it to
be executed:
- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `22352:22398` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Timeout context managers can be safely nested.
- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `990:1043` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: debug()
,
info()
,
warning()
,
error()
and
critical()

Split: `dev` · Review: `programmatic_candidate`

## PROF-0338 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. What do React Effects let a component synchronize with?
2. According to React Synchronizing with Effects, what does the document state about Synchronizing with an external system?
3. How does promise chaining order asynchronous operations?

**Reference answer:** 1. let you run some code after rendering so that you can synchronize your component with some system outside of React.
2. Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
3. A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `316:431` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: let you run some code after rendering so that you can synchronize your component with some system outside of React.
- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `9458:9576` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `1221:1415` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: A common need is to execute two or more asynchronous operations back to back, where each subsequent operation starts when the previous operation succeeds, with the result from the previous step.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0339 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. How many transaction isolation levels does the SQL standard define?
2. According to PostgreSQL Transaction Isolation, what can More complex usage do?
3. According to RFC 9110 HTTP Semantics, what does the document state about HTTP intermediaries?

**Reference answer:** 1. standard defines four levels of transaction isolation.
2. More complex usage can produce undesirable results in Read Committed mode.
3. HTTP intermediaries are inherently situated for on-path attacks.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `576:630` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: standard defines four levels of transaction isolation.
- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `8861:8935` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: More complex usage can produce undesirable results in Read Committed mode.
- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `367505:367569` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: HTTP intermediaries are inherently situated for on-path attacks.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0340 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. How does LangChain define an agent?
2. What role does middleware play in customizing a LangChain agent?
3. Which request does an MCP client send to discover available tools?

**Reference answer:** 1. An agent is a model calling tools in a loop until a given task is complete.
2. Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.
3. To discover available tools, clients send a tools/list request.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `0:75` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: An agent is a model calling tools in a loop until a given task is complete.
- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `23252:23413` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.
- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `1347:1410` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: To discover available tools, clients send a
tools/list
request.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0341 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. How does WHO define patient safety?
2. According to WHO Patient safety, what can Failure to correctly identify patients do?
3. What information should a patient record in a medicine list?

**Reference answer:** 1. Patient safety is defined as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."
2. Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.
3. Write down all of the medicines that you are taking, including the names of your medicines, how much you take, and when you take them.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `343:514` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Patient safety is
defined
as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `3815:3940` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.
- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `829:963` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: Write down all of the medicines that you are taking, including the names of your medicines, how much you take, and when you take them.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0342 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. What is a Docker volume?
2. According to Docker Volumes, what does the guidance require of The subdirectory?
3. When does Kubernetes begin running liveness and readiness probes if a startup probe is configured?

**Reference answer:** 1. Volumes are persistent data stores for containers, created and managed by Docker.
2. The subdirectory must exist in the volume before the volume is mounted to a container.
3. If a startup probe is configured, Kubernetes does not execute liveness or readiness probes until the startup probe succeeds,

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `107:188` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: Volumes are persistent data stores for containers, created and managed by
Docker.
- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `5873:5959` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The subdirectory must exist in the volume before the volume is mounted to a container.
- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `726:850` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: If a startup probe is configured, Kubernetes does not execute liveness or
readiness probes until the startup probe succeeds,

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0343 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What is the stated purpose of the NIST Cybersecurity Framework?
2. What default access-control policy does OWASP recommend for non-public resources?

**Reference answer:** 1. Helping organizations to better understand and improve their management of cybersecurity risk
2. Except for public resources, deny by default.

**Evidence:**

- [nist-csf](https://www.nist.gov/cyberframework) · extracted text `382:475` · SHA-256 `746cc27f2a2cfbda2374ace7bda15e3a356182e3f21aa7ea4911ad6c38291ae4`: Helping organizations to better understand and improve their management of cybersecurity risk
- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2412:2457` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Except for public resources, deny by default.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0344 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. Why is evaluating a model on the same data used for fitting methodologically wrong?
2. According to scikit-learn Cross-validation, what does the document state about Sorted groups?
3. According to pandas Group by, what does the document state about The Series name?

**Reference answer:** 1. Learning the parameters of a prediction function and testing it on the same data is a methodological mistake: a model that would just repeat the labels of the samples that it has just seen would have a perfect score but would fail to predict anything useful on yet-unseen data.
2. Sorted groups are iterated over and assigned to folds.
3. The Series name is used as the name for the column index.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `58:335` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Learning the parameters of a prediction function and testing it on the
same data is a methodological mistake: a model that would just repeat
the labels of the samples that it has just seen would have a perfect
score but would fail to predict anything useful on yet-unseen data.
- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `25159:25213` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: Sorted groups are iterated over and assigned to folds.
- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `66763:66820` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: The Series name is used as the name for the column index.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0345 · long_span_multi_source

**Question:** Answer each question and cite its source:
1. What does the FTC advise businesses to control when storing personal data?
2. According to FTC Start with Security, what does the document state about Network security?
3. According to WCAG 2.2 Non-text Content, what does the guidance require of Text alternatives and equivalents?

**Reference answer:** 1. limit access to the places where personal data is stored or to control who can use particular databases.
2. Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.
3. Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `6795:6899` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: limit access to the places where personal data is stored or to control who can use particular databases.
- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `34069:34233` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Network security is a critical consideration, but many of the same lessons apply to paperwork and physical media like hard drives, laptops, flash drives, and disks.
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `4262:4402` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: Text alternatives and equivalents should match the human language of the original content (normally the default human language of the page).

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0346 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to WHO Food safety, what does the document state about US$ 310 billion?
2. What are the reported consequences of health care-associated infections?

**Reference answer:** 1. US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
2. health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `212:320` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: US$ 310 billion is lost each year in productivity and medical expenses resulting from unsafe food worldwide.
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1583:1816` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths

Split: `dev` · Review: `programmatic_candidate`

## PROF-0347 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What exception is raised when an asyncio task is cancelled?
2. How does Python logging describe the importance assigned to an event?

**Reference answer:** 1. When a task is cancelled, asyncio.CancelledError will be raised in the task at the next opportunity.
2. Events also have an importance which the developer ascribes to the event; the importance can also be called the level or severity

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `7157:7257` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: When a task is cancelled,
asyncio.CancelledError
will be raised
in the task at the next opportunity.
- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `705:834` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: Events also have an importance which the
developer ascribes to the event; the importance can also be called the
level
or
severity

Split: `dev` · Review: `programmatic_candidate`

## PROF-0348 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to React Synchronizing with Effects, what does the document state about Synchronizing with an external system?
2. According to MDN Using promises, what does the document state about Simple promise chains?

**Reference answer:** 1. Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
2. Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `9458:9576` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: Synchronizing with an external system is not always instant, so you might want to skip doing it unless it’s necessary.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `9349:9458` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: Simple promise chains are best kept flat without nesting, as nesting can be a result of careless composition.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0349 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What outcome does Serializable isolation guarantee for concurrent transactions?
2. According to RFC 9110 HTTP Semantics, what does the document state about The From header field?

**Reference answer:** 1. The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.
2. The From header field is rarely sent by non-robotic user agents.

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `631:876` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: The most strict is Serializable, which is defined by the standard in a paragraph which says that any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order.
- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `193236:193300` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The From header field is rarely sent by non-robotic user agents.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0350 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to LangChain Agents, what can Hooks receive the current state and do?
2. What does the MCP tools specification recommend for human oversight of tool invocations?

**Reference answer:** 1. Hooks receive the current state and can return a dict of updates to merge back into it.
2. For trust & safety and security, there SHOULD always be a human in the loop with the ability to deny tool invocations.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `9860:9947` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Hooks receive the current state and can return a dict of updates to merge back into it.
- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `708:826` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: For trust & safety and security, there
SHOULD
always
be a human in the loop with the ability to deny tool invocations.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0351 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What is sepsis according to WHO?
2. What should a patient ask when receiving a prescription?

**Reference answer:** 1. Sepsis is a serious condition that happens when the body’s immune system has an extreme response to an infection.
2. When you get a prescription, ask the name of the medicine and check to make sure that the pharmacy gave you the right medicine.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1831:1944` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Sepsis is a serious condition that happens when the body’s immune system has an extreme response to an infection.
- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `570:697` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: When you get a prescription, ask the name of the medicine and check to make sure that the pharmacy gave you the right medicine.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0352 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to Docker Volumes, what does the guidance require of The subdirectory?
2. According to Kubernetes Liveness, Readiness, and Startup Probes, what does the document state about The probe's success?

**Reference answer:** 1. The subdirectory must exist in the volume before the volume is mounted to a container.
2. The probe's success is determined solely by the response status code, which is found in the response headers.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `5873:5959` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The subdirectory must exist in the volume before the volume is mounted to a container.
- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `16678:16787` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: The probe's success is determined solely by the response status code, which is found in the response headers.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0353 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. Which kinds of organizations is NIST CSF 2.0 intended to help reduce cybersecurity risks?
2. According to OWASP Broken Access Control, what does the document state about Admin rights?

**Reference answer:** 1. For industry, government, and organizations to reduce cybersecurity risks
2. Admin rights are required for access to the admin page.

**Evidence:**

- [nist-csf](https://www.nist.gov/cyberframework) · extracted text `740:813` · SHA-256 `746cc27f2a2cfbda2374ace7bda15e3a356182e3f21aa7ea4911ad6c38291ae4`: For industry, government, and organizations to reduce cybersecurity risks
- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `4112:4167` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: Admin rights are required for access to the admin page.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0354 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. How can scikit-learn quickly create a random training/test split?
2. According to pandas Group by, what does the document state about Another common data transform?

**Reference answer:** 1. In scikit-learn a random split into training and test sets can be quickly computed with the train_test_split helper function.
2. Another common data transform is to replace missing data with the group mean.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `845:970` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: In scikit-learn a random split into training and test sets
can be quickly computed with the
train_test_split
helper function.
- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `37214:37291` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Another common data transform is to replace missing data with the group mean.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0355 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. Who should receive administrative access under the FTC security guidance?
2. According to WCAG 2.2 Non-text Content, what does the document state about An image of a chart?

**Reference answer:** 1. Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.
2. An image of a chart is described in text in the paragraph after the chart.

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `8793:8931` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Administrative access, which lets a user make system-wide changes to your system, should be limited to the employees tasked with that job.
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `28875:28949` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: An image of a chart is described in text in the paragraph after the chart.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0356 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to WHO Food safety, what does the document state about Norovirus?
2. According to WHO Patient safety, what can Failure to correctly identify patients do?

**Reference answer:** 1. Norovirus is a common cause of foodborne infections that is characterized by nausea, explosive vomiting, watery diarrhoea and abdominal pain.
2. Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `3686:3827` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Norovirus is a common cause of foodborne infections that is characterized by nausea, explosive vomiting, watery diarrhoea and abdominal pain.
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `3815:3940` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Failure to correctly identify patients can be a root cause of many problems and has serious effects on health care provision.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0357 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to Python asyncio Tasks, what can Timeout context managers do?
2. What is logging used for in Python software?

**Reference answer:** 1. Timeout context managers can be safely nested.
2. Logging is a means of tracking events that happen when some software runs.

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `22352:22398` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Timeout context managers can be safely nested.
- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `359:433` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: Logging is a means of tracking events that happen when some software runs.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0358 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to React Synchronizing with Effects, what can The dependency array do?
2. How does MDN define a JavaScript Promise?

**Reference answer:** 1. The dependency array can contain multiple dependencies.
2. is an object representing the eventual completion or failure of an asynchronous operation.

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `13850:13905` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: The dependency array can contain multiple dependencies.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `39:129` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: is an object representing the eventual completion or failure of an asynchronous operation.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0359 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to PostgreSQL Transaction Isolation, what can More complex usage do?
2. According to RFC 9110 HTTP Semantics, what does the document state about The target of an HTTP request?

**Reference answer:** 1. More complex usage can produce undesirable results in Read Committed mode.
2. The target of an HTTP request is called a "resource".

**Evidence:**

- [postgres-isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · extracted text `8861:8935` · SHA-256 `793ccfa694351d8a833345ec8a87bf32869f9b72dab173957b2395876fca0945`: More complex usage can produce undesirable results in Read Committed mode.
- [rfc-http-semantics](https://www.rfc-editor.org/rfc/rfc9110.html) · extracted text `17937:17990` · SHA-256 `b89d9f4f91ddd7d3a37c87b144f97048a14859b03431bd1b759a5b0bafdd98fa`: The target of an HTTP request is called a "resource".

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0360 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What role does middleware play in customizing a LangChain agent?
2. How are individual MCP tools identified and described?

**Reference answer:** 1. Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.
2. Each tool is uniquely identified by a name and includes metadata describing its schema.

**Evidence:**

- [langchain-agents](https://docs.langchain.com/oss/python/langchain/agents) · extracted text `23252:23413` · SHA-256 `5c82e1d2ebfe68cfb110a0f3d23674da92110cc1bb9ca82b4a50a368189acf2c`: Middleware is the primitive for customization: each piece handles one concern, hooks into the agent loop at the right moment, and composes freely with any other.
- [mcp-tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · extracted text `229:316` · SHA-256 `0f27eccf260b8834c603c937e612da3eaf90c5d6d2161d0e4483154944dfb54f`: Each tool is uniquely identified by
a name and includes metadata describing its schema.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0361 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What are the reported consequences of health care-associated infections?
2. Where can medication errors occur, according to MedlinePlus?

**Reference answer:** 1. health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths
2. Errors can happen in the hospital, at the health care provider's office, at the pharmacy, or at home.

**Evidence:**

- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `1583:1816` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: health care-associated infections result in extended duration of hospital stays, long-standing disability, increased antimicrobial resistance, additional financial burden on patients, families and health systems, and avoidable deaths
- [medlineplus-medication-errors](https://medlineplus.gov/medicationerrors.html) · extracted text `412:513` · SHA-256 `cb91aaa8525188ea5225acd606cfb108259ad62801b875cdd25a173eda2a7e16`: Errors can happen in the hospital, at the health care provider's office, at the pharmacy, or at home.

Split: `dev` · Review: `programmatic_candidate`

## PROF-0362 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. In Docker's volume example, can one container access another container's logs?
2. According to Kubernetes Liveness, Readiness, and Startup Probes, what can Incorrect implementation of liveness probes do?

**Reference answer:** 1. The containers can't access the other container's logs.
2. Incorrect implementation of liveness probes can lead to cascading failures.

**Evidence:**

- [docker-volumes](https://docs.docker.com/engine/storage/volumes/) · extracted text `14540:14595` · SHA-256 `246af2023ba3606050372cd92233dcac59a9767ea78dc61c2f325a2b55f27759`: The containers can't access the other container's logs.
- [kubernetes-probes-en](https://kubernetes.io/docs/concepts/workloads/pods/probes/) · extracted text `1991:2066` · SHA-256 `48bdfb98ae2ffcaeaa7afb1e4fd99dfe4ce5720eb07dc3bbeeec21275a80014e`: Incorrect implementation of liveness probes can lead to cascading failures.

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0363 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What is the stated purpose of the NIST Cybersecurity Framework?
2. According to OWASP Broken Access Control, what does CORS misconfiguration allow?

**Reference answer:** 1. Helping organizations to better understand and improve their management of cybersecurity risk
2. CORS misconfiguration allows API access from unauthorized or untrusted origins.

**Evidence:**

- [nist-csf](https://www.nist.gov/cyberframework) · extracted text `382:475` · SHA-256 `746cc27f2a2cfbda2374ace7bda15e3a356182e3f21aa7ea4911ad6c38291ae4`: Helping organizations to better understand and improve their management of cybersecurity risk
- [owasp-access-control](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/) · extracted text `2023:2102` · SHA-256 `b04728c768d04209695599e0ccde1a13f5a5bcebca120185109c5d719efb5f1d`: CORS misconfiguration allows API access from unauthorized or untrusted origins.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0364 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. What is the purpose of holding out a test set in supervised learning?
2. According to pandas Group by, what does the document state about Another aggregation example?

**Reference answer:** 1. To avoid it, it is common practice when performing a (supervised) machine learning experiment to hold out part of the available data as a test set X_test, y_test
2. Another aggregation example is to compute the number of unique values of each group.

**Evidence:**

- [sklearn-cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) · extracted text `375:536` · SHA-256 `4aee2a3f6b733d9932e74aafd7f4c77a5c7abb965cbad00bfae8ae6b62709c1d`: To avoid it, it is common practice when performing
a (supervised) machine learning experiment
to hold out part of the available data as a
test set
X_test,
y_test
- [pandas-groupby](https://pandas.pydata.org/docs/user_guide/groupby.html) · extracted text `20466:20550` · SHA-256 `592c0e2e0f66405fdb4a5fcda50080b651509e1e88014789e4ab134741f9f399`: Another aggregation example is to compute the number of unique values of each group.

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0365 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to FTC Start with Security, what does the guidance require of Businesses?
2. What is the general WCAG requirement for non-text content presented to users?

**Reference answer:** 1. Businesses should consider other protections to help protect against password compromises – for example, multi-factor authentication or strong adaptive and salted hashing that has significant iterations of the hashing algorithm for each password.
2. non-text content that is presented to the user has a text alternative that serves the equivalent purpose

**Evidence:**

- [ftc-start-security](https://www.ftc.gov/business-guidance/resources/start-security-guide-business) · extracted text `12058:12304` · SHA-256 `60179e8ac0d378a881780d6c56365c23668ec74f4e9b407f1859661196e57cee`: Businesses should consider other protections to help protect against password compromises – for example, multi-factor authentication or strong adaptive and salted hashing that has significant iterations of the hashing algorithm for each password.
- [w3c-non-text-content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html) · extracted text `292:396` · SHA-256 `1e1d224cb27b26777635685c2baf4a49f2f44b7657ca7611a9f3f3b7e9c60b44`: non-text content
that is presented to the user has a
text alternative
that serves the equivalent purpose

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0366 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to WHO Food safety, what does the document state about Certain parasites?
2. How does WHO define patient safety?

**Reference answer:** 1. Certain parasites are transmitted to humans exclusively through food, while for others, food represents a major pathway of infection.
2. Patient safety is defined as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."

**Evidence:**

- [who-food-safety](https://www.who.int/news-room/fact-sheets/detail/food-safety/) · extracted text `4397:4530` · SHA-256 `f82f86b03bc8cd65cc7ce824a590d02bd2c7554639b16dc65de355867bfedc6f`: Certain parasites are transmitted to humans exclusively through food, while for others, food represents a major pathway of infection.
- [who-patient-safety](https://www.who.int/news-room/fact-sheets/detail/patient-safety) · extracted text `343:514` · SHA-256 `9e707da4537b06dedeeedf4e77f0605448780c7191f31ce165f57573ef2eba7a`: Patient safety is
defined
as “the absence of preventable harm to a patient and reduction of risk of unnecessary harm associated with health care to an acceptable minimum."

Split: `dev` · Review: `programmatic_candidate`

## PROF-0367 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to Python asyncio Tasks, what does the document state about Tasks?
2. Which logger methods does the Python Logging HOWTO list for common severity levels?

**Reference answer:** 1. Tasks are used to run coroutines in event loops.
2. debug() , info() , warning() , error() and critical()

**Evidence:**

- [py-asyncio](https://docs.python.org/3.13/library/asyncio-task.html) · extracted text `32015:32063` · SHA-256 `2eb97c0b3d799038557599fa99c1de61b5c24b06c4c9b23c1cc47855b7561ab0`: Tasks are used to run coroutines in event loops.
- [python-logging](https://docs.python.org/3.13/howto/logging.html) · extracted text `990:1043` · SHA-256 `a021f434216cb182931a91accc440391364d43c7d5e3ed6ea5670f0a27677849`: debug()
,
info()
,
warning()
,
error()
and
critical()

Split: `dev` · Review: `programmatic_candidate`

## PROF-0368 · multi_source_multi_intent

**Question:** Answer each question and cite its source:
1. According to React Synchronizing with Effects, what does the guidance require of The cleanup function?
2. What does the then() function return?

**Reference answer:** 1. The cleanup function should stop or undo whatever the Effect was doing.
2. then() function returns a new promise , different from the original:

**Evidence:**

- [react-effects](https://react.dev/learn/synchronizing-with-effects) · extracted text `20749:20820` · SHA-256 `5359697d2b95878242ea43fc991519872a80e6e0e850290388b0220492a83239`: The cleanup function should stop or undo whatever the Effect was doing.
- [mdn-promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises) · extracted text `2008:2076` · SHA-256 `f3a9f431d4ceb34b8e0286bef4473ae0f234179b1969efe757008be8d78d59d2`: then()
function returns a
new promise
, different from the original:

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0369 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. Vue 的浅层 ref 仅追踪哪种访问？
2. Vue 的计算属性值在什么情况下重新计算？

**Reference answer:** 1. 对于浅层 ref，只有 .value 的访问会被追踪。
2. 一个计算属性仅会在其响应式依赖更新时才重新计算。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `4751:4778` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 对于浅层 ref，只有
.value
的访问会被追踪。
- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2575:2599` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 一个计算属性仅会在其响应式依赖更新时才重新计算。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0370 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. Kubernetes Deployment 的 pod-template-hash 标签起什么作用？
2. Kubernetes HTTP 探针依据响应中的什么信息判断成功？

**Reference answer:** 1. 此标签可确保 Deployment 的子 ReplicaSet 不重叠。
2. 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

**Evidence:**

- [kubernetes-deployment-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/controllers/deployment/) · extracted text `4019:4055` · SHA-256 `3b75a6fa4bbaebdd9b87f6262527e5d906976e08043734590f327eb3ecb8c15e`: 此标签可确保 Deployment 的子 ReplicaSet 不重叠。
- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `7980:8011` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 探针的成功与否仅由响应状态码决定，状态码可以在响应标头中找到。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0371 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 阿里云百炼列出的三种核心应用构建模式是什么？
2. 子账号通过阿里云 API 操作知识库之前需要具备什么权限和业务空间条件？

**Reference answer:** 1. 三种核心应用构建模式：智能体（Agent）、工作流（Workflow） 和高代码应用 。
2. 子账号 （主账号不需要）需获取 API 权限 （AliyunBailianDataFullAccess 策略），并加入一个业务空间 ，然后才能通过阿里云 API 操作知识库。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `52:97` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 三种 核心应用构建模式：智能体（Agent）、工作流（Workflow） 和高代码应用 。
- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `155:243` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 子账号
（主账号不需要）需获取
API
权限
（AliyunBailianDataFullAccess
策略），并
加入一个业务空间
，然后才能通过阿里云
API
操作知识库。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0372 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？
2. 根据《中华人民共和国劳动合同法》，除本法第二十二条和第二十三条规定的情形外，用人单位有哪些禁止性规定？
3. 根据《中华人民共和国民法典》第七百八十九条，建设工程合同有哪些要求？

**Reference answer:** 1. 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
2. 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。
3. 第七百八十九条建设工程合同应当采用书面形式。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `3337:3380` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `74740:74763` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第七百八十九条　建设工程合同应当采用书面形式。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0373 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《抗菌药物临床应用管理办法》所称抗菌药物包括哪些用途，不包括哪些药物？
2. 《医院感染管理办法》对住院床位总数在100张以上的医院设置感染管理组织有何要求？

**Reference answer:** 1. 本办法所称抗菌药物是指治疗细菌、支原体、衣原体、立克次体、螺旋体、真菌等病原微生物所致感染性疾病病原的药物，不包括治疗结核病、 寄生虫病和各种病毒所致感染性疾病的药物以及具有抗菌作用的中药制剂。
2. 住院床位总数在100 张以上的医院应当设立医院感染管理委员会和独立的医院感染管理部门。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `200:304` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 本办法所称抗菌药物是指治疗细菌、支

原体、衣原体、立克次体、螺旋体、真菌等病原微生

物所致感染性疾病病原的药物，不包括治疗结核病、

寄生虫病和各种病毒所致感染性疾病的药物以及具

有抗菌作用的中药制剂。
- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `598:682` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 住院床位总数在100 张以上的医院应当

设立医院感染管理委员会和独立的医院感染管理部




- 2 -

 国家卫生健康委员会发布
 国家卫生健康委员会规章

门。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0374 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《医院感染管理办法》如何定义医院感染管理？
2. 《医务人员手卫生规范》规定的洗手过程是什么？

**Reference answer:** 1. 医院感染管理是各级卫生行政部门、医疗机构及医务人员针对诊疗活动中存在的医院感染、 医源性感染及相关的危险因素进行的预防、诊断和控制活动。
2. 医务人员用流动水和洗手液（肥皂）揉搓冲洗双手，去除手部皮肤污垢、碎屑和部分微生物的过程。

**Evidence:**

- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `194:267` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 医院感染管理是各级卫生行政部门、医

疗机构及医务人员针对诊疗活动中存在的医院感染、

医源性感染及相关的危险因素进行的预防、诊断和控

制活动。
- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `1942:1986` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 医务人员用流动水和洗手液（肥皂）揉搓冲洗双手，去除手部皮肤污垢、碎屑和部分微生物的过程。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0375 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，食品生产经营者有哪些要求？
2. 根据《中华人民共和国食品安全法》第五十一条，食品生产企业有哪些要求？
3. 根据《中华人民共和国电子商务法》，国家进出口管理部门有哪些要求？

**Reference answer:** 1. 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
2. 第五十一条食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。
3. 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `1049:1116` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `9678:9792` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第五十一条　食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7823:7912` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0376 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，财务会计报告使用者包括哪些内容？
2. 根据《企业会计准则——基本准则》，前款所指的企业过去的交易或者事项包括哪些内容？
3. 《个人信息保护法》列举了哪些个人信息处理活动？

**Reference answer:** 1. 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
2. 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。
3. 个人信息的处理包括个人信息的收集、存储、使用、加工、 传输、提供、公开、删除等。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `551:585` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1438:1476` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。
- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `588:629` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息的处理包括个人信息的收集、存储、使用、加工、

传输、提供、公开、删除等。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0377 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第四条，各级人民政府有哪些要求？
2. 根据《中华人民共和国教师法》，不具备本法规定的教师资格学历的公民，申请获取教师资格有哪些要求？
3. 根据《中小学教育惩戒规则（试行）》，各地可以采取什么做法？

**Reference answer:** 1. 第四条各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
2. 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。
3. 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `549:618` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第四条 各级人民政府应当采取措施，加强教师的思想政治教育和业务培训，改善教师的工作条件和生活条件，保障教师的合法权益，提高教师的社会地位。
- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `1856:1896` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3817:3850` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 各地可以结合本地实际，制定本地方实施细则或者指导学校制定实施细则。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0378 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《2025年工业和信息化标准工作要点》提出制定多少项以上行业标准？
2. 根据《中华人民共和国安全生产法》第八十八条，任何单位和个人有哪些禁止性规定？

**Reference answer:** 1. 制定行业标准1800 项以上
2. 第八十八条任何单位和个人不得阻挠和干涉对事故的依法调查处理。

**Evidence:**

- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `351:366` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 制定行
业标准1800 项以上
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `14001:14032` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 第八十八条　任何单位和个人不得阻挠和干涉对事故的依法调查处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0379 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，发明指什么？
2. 根据《中华人民共和国专利法》，授予专利权的外观设计有哪些禁止性规定？
3. 根据《中华人民共和国民法典》第七百八十九条，建设工程合同有哪些要求？

**Reference answer:** 1. 发明，是指对产品、方法或者其改进所提出的新的技术方案。
2. 授予专利权的外观设计不得与他人在申请日以前已经取得的合法权利相冲突。
3. 第七百八十九条建设工程合同应当采用书面形式。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `576:603` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 发明，是指对产品、方法或者其改进所提出的新的技术方案。
- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `3450:3484` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 授予专利权的外观设计不得与他人在申请日以前已经取得的合法权利相冲突。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `74740:74763` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第七百八十九条　建设工程合同应当采用书面形式。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0380 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《个人信息保护法》如何定义个人信息？
2. 根据《中华人民共和国电子商务法》，国家进出口管理部门有哪些要求？

**Reference answer:** 1. 个人信息是以电子或者其他方式记录的与已识别或者可识别的自然人有关的各种信息，不包括匿名化处理后的信息。
2. 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `530:585` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息是以电子或者其他方式记录的与已识别

或者可识别的自然人有关的各种信息，不包括匿名化处理后的信

息。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `7823:7912` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 国家进出口管理部门应当推进跨境电子商务海关申报、纳税、检验检疫等环节的综合服务和监管体系建设，优化监管流程，推动实现信息共享、监管互认、执法互助，提高跨境电子商务服务和监管效率。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0381 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. Vue 响应式对象与普通对象相比，属性访问和修改有什么区别？
2. Vue 文档如何限定计算属性 getter 的职责？

**Reference answer:** 1. 响应式对象是 JavaScript 代理 ，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。
2. 计算属性的 getter 应只做计算而没有任何其他的副作用

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `5551:5629` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 响应式对象是
JavaScript 代理
，其行为就和普通对象一样。不同的是，Vue 能够拦截对响应式对象所有属性的访问和修改，以便进行依赖追踪和触发更新。
- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `5134:5163` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性的 getter 应只做计算而没有任何其他的副作用

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0382 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. Kubernetes Deployment 更新时默认至少保持多少比例的所需 Pod 运行？
2. 根据《Kubernetes 存活、就绪和启动探针》，存活探针有哪些要求？

**Reference answer:** 1. Deployment 可确保在更新时仅关闭一定数量的 Pod。默认情况下，它确保至少所需 Pod 的 75% 处于运行状态（最大不可用比例为 25%）。
2. 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。

**Evidence:**

- [kubernetes-deployment-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/controllers/deployment/) · extracted text `5749:5825` · SHA-256 `3b75a6fa4bbaebdd9b87f6262527e5d906976e08043734590f327eb3ecb8c15e`: Deployment 可确保在更新时仅关闭一定数量的 Pod。默认情况下，它确保至少所需
Pod 的 75% 处于运行状态（最大不可用比例为 25%）。
- [kubernetes-probes-zh](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/probes/) · extracted text `667:704` · SHA-256 `dcc19d8384fd45258dc7ecbb9156ece55dc4a6f2aee309a4dd7082377f7ea584`: 存活探针必须经过仔细配置，确保其真正能够指示不可恢复的应用故障，例如死锁。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0383 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 百炼智能体应用如何理解用户意图并完成任务？
2. 阿里云百炼知识库功能分别支持中国站和国际站的哪些地域？

**Reference answer:** 1. 由提示词驱动，能够自主理解用户意图、制定决策，并调用知识库、MCP 服务等外部工具来完成任务。
2. 知识库相关功能在中国站仅支持华北 2（北京） 地域，在国际站仅支持新加坡地域开通和使用，其他地域如德国（法兰克福）等均不支持知识库功能。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `175:222` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 由提示词驱动，能够自主理解用户意图、制定决策，并调用知识库、MCP 服务等外部工具来完成任务。
- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `78:149` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 知识库相关功能在中国站仅支持
华北
2（北京）
地域，在国际站仅支持
新加坡
地域开通和使用，其他地域如德国（法兰克福）等均不支持知识库功能。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0384 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，订立劳动合同有哪些要求？
2. 根据《中华人民共和国劳动合同法》，除本法第二十二条和第二十三条规定的情形外，用人单位有哪些禁止性规定？
3. 根据《中华人民共和国民法典》第九百九十二条，人格权有哪些禁止性规定？

**Reference answer:** 1. 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
2. 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。
3. 第九百九十二条人格权不得放弃、转让或者继承。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `588:623` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 订立劳动合同，应当遵循合法、公平、平等自愿、协商一致、诚实信用的原则。
- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `3337:3380` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `94789:94812` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百九十二条　人格权不得放弃、转让或者继承。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0385 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 抗菌药物临床应用按哪些因素分级，分为哪三级？
2. 《医院感染管理办法》如何定义医院感染管理？

**Reference answer:** 1. 抗菌药物临床应用实行分级管理。根据安全性、疗效、细菌耐药性、价格等因素，将抗菌药物分为三级：非限制使用级、限制使用级与特殊使用级。
2. 医院感染管理是各级卫生行政部门、医疗机构及医务人员针对诊疗活动中存在的医院感染、 医源性感染及相关的危险因素进行的预防、诊断和控制活动。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `493:564` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 抗菌药物临床应用实行分级管理。根据

安全性、疗效、细菌耐药性、价格等因素，将抗菌药

物分为三级：非限制使用级、限制使用级与特殊使用

级。
- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `194:267` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 医院感染管理是各级卫生行政部门、医

疗机构及医务人员针对诊疗活动中存在的医院感染、

医源性感染及相关的危险因素进行的预防、诊断和控

制活动。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0386 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《医院感染管理办法》对住院床位总数在100张以上的医院设置感染管理组织有何要求？
2. 《医务人员手卫生规范》对医疗机构的手卫生制度和设施有哪些要求？

**Reference answer:** 1. 住院床位总数在100 张以上的医院应当设立医院感染管理委员会和独立的医院感染管理部门。
2. 医疗机构应制定并落实手卫生管理制度，配备有效、便捷、适宜的手卫生设施。

**Evidence:**

- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `598:682` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 住院床位总数在100 张以上的医院应当

设立医院感染管理委员会和独立的医院感染管理部




- 2 -

 国家卫生健康委员会发布
 国家卫生健康委员会规章

门。
- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `2808:2843` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 医疗机构应制定并落实手卫生管理制度，配备有效、便捷、适宜的手卫生设施。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0387 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，食品生产经营者有哪些要求？
2. 根据《中华人民共和国食品安全法》第五十一条，食品生产企业有哪些要求？
3. 根据《中华人民共和国电子商务法》，电子商务平台经营者为经营者之间的电子商务提供服务有哪些要求？

**Reference answer:** 1. 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
2. 第五十一条食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。
3. 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `1049:1116` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 食品生产经营者应当依照法律、法规和食品安全标准从事生产经营活动，保证食品安全，诚信自律，对社会和公众负责，接受社会监督，承担社会责任。
- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `9678:9792` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 第五十一条　食品生产企业应当建立食品出厂检验记录制度，查验出厂食品的检验合格证和安全状况，如实记录食品的名称、规格、数量、生产日期或者生产批号、保质期、检验合格证号、销售日期以及购货者名称、地址、联系方式等内容，并保存相关凭证。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `5095:5175` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0388 · long_span_multi_source

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》，财务会计报告使用者包括哪些内容？
2. 根据《企业会计准则——基本准则》，前款所指的企业过去的交易或者事项包括哪些内容？
3. 根据《中华人民共和国个人信息保护法》，个人信息处理者有哪些要求？

**Reference answer:** 1. 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
2. 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。
3. 个人信息处理者应当提供便捷的撤回同意的方式。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `551:585` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 财务会计报告使用者包括投资者、债权人、政府及其有关部门和社会公众等。
- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1438:1476` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 前款所指的企业过去的交易或者事项包括购买、生产、建造行为或其他交易或者事项。
- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `1765:1787` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息处理者应当提供便捷的撤回同意的方式。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0389 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》，不具备本法规定的教师资格学历的公民，申请获取教师资格有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，教师因实施教育惩戒与学生及其家长发生纠纷，学校有哪些要求？

**Reference answer:** 1. 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。
2. 教师因实施教育惩戒与学生及其家长发生纠纷，学校应当及时进行处理，教师无过错的，不得因教师实施教育惩戒而给予其处分或者其他不利处理。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `1856:1896` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 不具备本法规定的教师资格学历的公民，申请获取教师资格，必须通过国家教师资格考试。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `2970:3035` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 教师因实施教育惩戒与学生及其家长发生纠纷，学校应当及时进行处理，教师无过错的，不得因教师实施教育惩戒而给予其处分或者其他不利处理。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0390 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《2025年工业和信息化标准工作要点》提出如何利用大模型赋能标准化建设？
2. 根据《中华人民共和国安全生产法》，生产经营单位有哪些禁止性规定？

**Reference answer:** 1. 探索推进“人工智能+标准化”，利用人工智能大模型赋能标准化建设，推动人工智能技术在标准预研、编制、宣贯和实施推广等全生命周期的应用，提高标准制定效率，推动标准落地实施。
2. 生产经营单位不得使用应当淘汰的危及生产安全的工艺、设备。

**Evidence:**

- [miit-standards-zh](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/e0917b45c38344ed8add9cba98cec1ba.pdf) · extracted text `1213:1306` · SHA-256 `9e2a0d03f98b0fadeeca6c6929d997dd030fe07fdd23e9d60844065f66065353`: 探索推进“人工智能+标
准化”，利用人工智能大模型赋能标准化建设，推动人工智能


 2
技术在标准预研、编制、宣贯和实施推广等全生命周期的应

用，提高标准制定效率，推动标准落地实施。
- [safety-production-law-zh](https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml) · extracted text `6434:6462` · SHA-256 `9f6e651f3982d1342f054433a0dc766ca97946acac8796d00219fbc85189b563`: 生产经营单位不得使用应当淘汰的危及生产安全的工艺、设备。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0391 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国专利法》，专利代理机构有哪些要求？
2. 根据《中华人民共和国民法典》第九百九十二条，人格权有哪些禁止性规定？

**Reference answer:** 1. 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。
2. 第九百九十二条人格权不得放弃、转让或者继承。

**Evidence:**

- [patent-law-zh](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html) · extracted text `2468:2547` · SHA-256 `0c6d1be70be7569b29671368c5c5a9c4e39560ccb5bcb8bf9f4304e3d5d0ab11`: 专利代理机构应当遵守法律、行政法规，按照被代理人的委托办理专利申请或者其他专利事务；对被代理人发明创造的内容，除专利申请已经公布或者公告的以外，负有保密责任。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `94789:94812` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百九十二条　人格权不得放弃、转让或者继承。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0392 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《个人信息保护法》要求个人信息处理遵循哪些原则？
2. 根据《中华人民共和国电子商务法》，电子商务平台经营者为经营者之间的电子商务提供服务有哪些要求？

**Reference answer:** 1. 处理个人信息应当遵循合法、正当、必要和诚信原则
2. 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

**Evidence:**

- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `636:661` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 处理个人信息应当遵循合法、正当、必要和诚信原

则
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `5095:5175` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者为经营者之间的电子商务提供服务，应当遵守法律、行政法规和国家有关规定，不得采取集中竞价、做市商等集中交易方式进行交易，不得进行标准化合约交易。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0393 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《Vue 响应式基础》，和组件实例上的其他属性一样，方法也可以采取什么做法？
2. Vue 计算属性如何跟踪依赖？

**Reference answer:** 1. 和组件实例上的其他属性一样，方法也可以在模板上被访问。
2. 计算属性会自动追踪响应式依赖。

**Evidence:**

- [vue-reactivity-zh](https://cn.vuejs.org/guide/essentials/reactivity-fundamentals) · extracted text `3964:3991` · SHA-256 `889648d90fd393c7a039175ca19a1a805a577646b1b868e67b255bf682b4fb8c`: 和组件实例上的其他属性一样，方法也可以在模板上被访问。
- [vue-computed-zh](https://cn.vuejs.org/guide/essentials/computed) · extracted text `2064:2079` · SHA-256 `7cefb944d132866d066e442ce435e2526f9f3e9559237cf2c841abc36699995c`: 计算属性会自动追踪响应式依赖。

Split: `holdout_candidate` · Review: `programmatic_candidate`

## PROF-0394 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 百炼工作流应用如何组织多步骤复杂任务？
2. 阿里云百炼的这份知识库 API 文档适用于哪类知识库？

**Reference answer:** 1. 通过可视化节点编排，能够将多步骤复杂任务串联成稳定可控、可复现的执行链路。
2. 本文档仅适用于文档搜索类知识库。

**Evidence:**

- [aliyun-agent-zh](https://help.aliyun.com/zh/model-studio/application-introduction) · extracted text `278:315` · SHA-256 `cc05ff8b35c2e0045197859552d1de46172f95c113e111d9ab2476d74583997b`: 通过可视化节点编排，能够将多步骤复杂任务串联成稳定可控、可复现的执行链路。
- [aliyun-rag-zh](https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide) · extracted text `58:74` · SHA-256 `08622152e7ba7c57a5feb13077347b345c98206b001a48e26a552c2089806283`: 本文档仅适用于文档搜索类知识库。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0395 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国劳动合同法》，劳动者在试用期内提前三日通知用人单位可以采取什么做法？
2. 根据《中华人民共和国民法典》第九百三十三条，委托人或者受托人可以采取什么做法？

**Reference answer:** 1. 劳动者在试用期内提前三日通知用人单位，可以解除劳动合同。
2. 第九百三十三条委托人或者受托人可以随时解除委托合同。

**Evidence:**

- [labor-contract-law-zh](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html) · extracted text `4204:4232` · SHA-256 `1abc1c369be024cbf202ba8d24ae0b6283aa14b7357e2236dde7899e2b09e306`: 劳动者在试用期内提前三日通知用人单位，可以解除劳动合同。
- [civil-code-zh](https://www.gz.gov.cn/attachment/6/6824/6824798/7364356.pdf) · extracted text `88977:89004` · SHA-256 `f689c1904fb4c15bdbae8f81ad3bdb8e9e5b55c4971c20baab027d9514387571`: 第九百三十三条　委托人或者受托人可以随时解除委托合同。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0396 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 抗菌药物临床应用应遵循什么原则？
2. 《医院感染管理办法》对住院床位总数在100张以上的医院设置感染管理组织有何要求？

**Reference answer:** 1. 抗菌药物临床应用应当遵循安全、有效、经济的原则。
2. 住院床位总数在100 张以上的医院应当设立医院感染管理委员会和独立的医院感染管理部门。

**Evidence:**

- [antimicrobial-use-zh](https://www.nhc.gov.cn/wjw/c100221/202201/413f7b67607949dfa9e3d881313bea5d/files/%E6%8A%97%E8%8F%8C%E8%8D%AF%E7%89%A9%E4%B8%B4%E5%BA%8A%E5%BA%94%E7%94%A8%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `460:486` · SHA-256 `fb59e27f91b048760c82982e1aaf837018d3d3f2c2fed5abd5a9187f2e445d13`: 抗菌药物临床应用应当遵循安全、有

效、经济的原则。
- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `598:682` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 住院床位总数在100 张以上的医院应当

设立医院感染管理委员会和独立的医院感染管理部




- 2 -

 国家卫生健康委员会发布
 国家卫生健康委员会规章

门。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0397 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 《医院感染管理办法》如何定义医院感染管理？
2. 《医务人员手卫生规范》如何定义手卫生？

**Reference answer:** 1. 医院感染管理是各级卫生行政部门、医疗机构及医务人员针对诊疗活动中存在的医院感染、 医源性感染及相关的危险因素进行的预防、诊断和控制活动。
2. 为医务人员在从事职业活动过程中的洗手、卫生手消毒和外科手消毒的总称。

**Evidence:**

- [infection-management-zh](https://www.nhc.gov.cn/wjw/c100221/202201/793c3dae63ca49b08dda27b03f9e8fd6/files/%E5%8C%BB%E9%99%A2%E6%84%9F%E6%9F%93%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf) · extracted text `194:267` · SHA-256 `d46242c8de0cbf448e4d1c507010ce5ddf2c653bdbcf6faee7d960cc60065ba8`: 医院感染管理是各级卫生行政部门、医

疗机构及医务人员针对诊疗活动中存在的医院感染、

医源性感染及相关的危险因素进行的预防、诊断和控

制活动。
- [hand-hygiene-zh](https://www.nhc.gov.cn/fzs/c100048/201912/2d76e0867a514056be5bfc3b21221e7d/files/1733125444510_79069.pdf) · extracted text `1881:1915` · SHA-256 `f89613b9def7fcff563d0e88f7e345296987a5820ba058f643640eb519ec8087`: 为医务人员在从事职业活动过程中的洗手、卫生手消毒和外科手消毒的总称。

Split: `calibration` · Review: `programmatic_candidate`

## PROF-0398 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国食品安全法》，专供婴幼儿和其他特定人群的主辅食品，其标签还有哪些要求？
2. 根据《中华人民共和国电子商务法》，电子商务平台经营者有哪些要求？

**Reference answer:** 1. 专供婴幼儿和其他特定人群的主辅食品，其标签还应当标明主要营养成分及其含量。
2. 电子商务平台经营者应当依照税收征收管理法律、行政法规的规定，向税务部门报送平台内经营者的身份信息和与纳税有关的信息，并应当提示依照本法第十条规定不需要办理市场主体登记的电子商务经营者依照本法第十一条第二款的规定办理税务登记。

**Evidence:**

- [food-safety-law-zh](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105) · extracted text `12561:12598` · SHA-256 `e85c5335c18b0d9ab7bf18a707e18824c91322a9f8cf51d2e7542c7e0bfb8f4a`: 专供婴幼儿和其他特定人群的主辅食品，其标签还应当标明主要营养成分及其含量。
- [ecommerce-law-samr-zh](https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_d337c3291e8b40459ca03dea54395856.html) · extracted text `3016:3128` · SHA-256 `f104ad4d4bd334e08413adb274d0b8b11c6dfc09352ef1c12a1714c91c72738d`: 电子商务平台经营者应当依照税收征收管理法律、行政法规的规定，向税务部门报送平台内经营者的身份信息和与纳税有关的信息，并应当提示依照本法第十条规定不需要办理市场主体登记的电子商务经营者依照本法第十一条第二款的规定办理税务登记。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0399 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《企业会计准则——基本准则》第二十三条，负债指什么？
2. 《个人信息保护法》如何定义个人信息？

**Reference answer:** 1. 第二十三条负债是指企业过去的交易或者事项形成的、预期会导致经济利益流出企业的现时义务。
2. 个人信息是以电子或者其他方式记录的与已识别或者可识别的自然人有关的各种信息，不包括匿名化处理后的信息。

**Evidence:**

- [accounting-basic-zh](https://xj.mof.gov.cn/caizhengjiancha/200805/t20080524_40447.htm) · extracted text `1751:1794` · SHA-256 `c0fdf7cfdb5e2a2b45ba6f3e67439f990894dae06914ce9eecde3253197c236b`: 第二十三条负债是指企业过去的交易或者事项形成的、预期会导致经济利益流出企业的现时义务。
- [privacy-law-zh](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3250/site/attach/0/dba5604e86e84261a3f68656af8570d0.pdf) · extracted text `530:585` · SHA-256 `abeb02805b6e83f14b403abb5428d4375f0cc75dee1a3beabb9705d41d48e05e`: 个人信息是以电子或者其他方式记录的与已识别

或者可识别的自然人有关的各种信息，不包括匿名化处理后的信

息。

Split: `dev` · Review: `programmatic_candidate`

## PROF-0400 · multi_source_multi_intent

**Question:** 请分别回答以下问题，并说明各自依据：
1. 根据《中华人民共和国教师法》第十五条，各级师范学校毕业生有哪些要求？
2. 根据《中小学教育惩戒规则（试行）》，学生申诉委员会有哪些要求？

**Reference answer:** 1. 第十五条各级师范学校毕业生，应当按照国家有关规定从事教育教学工作。
2. 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

**Evidence:**

- [teachers-law-zh](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html) · extracted text `2243:2277` · SHA-256 `2806c28735724ad9047a161f91e494717ae3c5315811a37dc96bc8089515e65c`: 第十五条 各级师范学校毕业生，应当按照国家有关规定从事教育教学工作。
- [education-discipline-zh](https://www.moe.gov.cn/srcsite/A02/s5911/moe_621/202012/t20201228_507882.html) · extracted text `3564:3618` · SHA-256 `f18f93402cb64d92908c3f02e1740221e4868ea8142d99ecfa15c7d42a9b7c5a`: 学生申诉委员会应当对学生申诉的事实、理由等进行全面审查，作出维持、变更或者撤销原教育惩戒或者纪律处分的决定。

Split: `holdout_candidate` · Review: `programmatic_candidate`
