from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.chains import RetrievalQA

class Retriever:   
    def __init__(self, db):
        self.db = db

    def retrieve(self, query, k=4):
        retriever = self.db.as_retriever(search_type="similarity", search_kwargs={"k": k})
        return retriever

    def generate(self, query, llm, k=4):
        retriever = self.retrieve(query, k)
        source_documents = retriever.invoke(query)
        template = """
        Answer questions based on the following context:
        {context}

        Question: {input}
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": source_documents, "input": query})
        return response, source_documents
    
    def generate_with_message(self, query, llm, k=4):
        retriever = self.retrieve(query, k)
        source_documents = retriever.invoke(query)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{context}"),
            ("human", "{input}"),
        ])
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": source_documents, "input": query})
        return response, source_documents

    def generate_with_qa(self, query, llm, k=4):
        retriever = self.retrieve(query, k)
        qa = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            chain_type="stuff",
            return_source_documents=True,
            )
        result = qa.invoke({"query": query})
        return result["result"], result["source_documents"]
    