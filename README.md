# Fraudit

## Inspiration
Fraudit is a platform for democratizing investing for retail investors. Hedge funds have teams of analysts that scrape news outlets, historical stock prices, and SEC filings to create reports about the stock market. Our platform orchestrates a multi-agent system to analyze SEC fraud, overall stock health, and public sentiment to generate market reports that rival hedge funds. 

## Key features
- Multi-agent system for synthesizing a financial report
- Industry-grade stock health prediction with Sharpe, Sortino, Alpha, Beta, VaR, CVaR
- Industry-grade SEC fraud detection with Beneish Z-Score, Accruals Ratio, Altman Z-Score 
- News Sentiment analysis agent
- SEC analysis agent
- Stock Health analysis agent
- Alert users of fraudulent stocks via a phone call
- Analyze insider trading patterns

## How we built it
Styling: HTML/CSS/JavaScript, mocked up in Figma Make  
Backend: FastAPI, Databricks Data Lake  
AI: Langchain, Google Gemini  
Accessibility: WACG-compliant design   
DataAPIs: sec-api, Yahoo Finance API, Google Gemini API  
Deployment: Cloudflare  
## Challenges we ran into
 - Converting the pipeline into ways Databricks could be used
 - Running the agentic models
 - Parsing SEC documents and mapping tags to features

## Accomplishments that we're proud of
- Deploying a Multi-agent system
- Coming up with a composite score
- Creating a user account system that automatically calls logged in investors

## What we learned
I'm glad we learned a lot about financial auditing, including the importance of 10Ks, 8Ks, and Form 4s that companies file. More than that, we learned how to skim texts and extract the most useful features out of these documents to feed to a pipeline. Of course, this pipeline wasn't easy either; we've previously heard tales of utilizing a multi-agent system to do tasks. However, we had never actually worked with them before. After using them, we realized that they have a rather niche case in which we need multiple features to be collected indepedently of each other, but is rather not pertitient otherwise.

## What's next for Fraudit
Y-Combinator
