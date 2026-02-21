# hacklytics-2026

# Inspiration

- Millions of dollars to hire analysts to find meaning from signals(SEC reports, Supply chain, job postings, options flow, stock trends). 
- retail investers (average joe) doesn't have these benefits. 
- We propose using agentic AI to research a stock and provide insights for if an stock is good to buy or not. 
- Extenstion Generate a portfolio of stocks to invest in given a starting budget. Final thing if everything else goes. well. 

- Our final report should include 
  * Graph of Sentiment over past N days highlight spikes (i think these are just local mins/maxes)
  * Quantitative metrics: 
    * Beneish M-score
    * Altman Z-Score
  * Written report explaning quantitative metrics and the sloppahs expert opinion
  * maybe suggest alternative stocks or stocks with high overall scores that have been queried before. 



- Our input Data is 
  * SEC(10-K, 10-Q, 8-K, Form 4) (Essential)
  * News (Essential)
  * Reddit 
  * Job Postings
  * Options Flow 
  * Short Interest +
  * Price/Volume + 
  * Earnings Call Transcripts

- We cache Intuits data to use while we are traning the model. Then we can test on any other fortune 500. assuming we don't crush our rate limits

## Muti-Agent system
Orchestrator agent (generic): plan work flow and dispatch sub agents
Sentiment Agent: Scrape reddit, news, and classifies sentiment over past 30 days. Flag unusual spikes in sentiment. 
Insider&Options


## Team Roles  
Kevius John Finance Open to doing data. : Quantitative metrics, Analyze supply chain trends if availible, Industry benchmark if possible, Analyze stock trends.  
Toby: If no one else wants to do frontend I can. I can also deal with data stuff.  
Ryon: 
Wyatt: 

Availible Roles: Frontend, Data pipeline (gives the rest of the team clean standardized data), Orchestrate agents&Public sentiment

Ok so -I'm thinking we Pivot from investing or at least reccomending stocks. to building a stock risk report by looking at public sentiment about a company (News, job postings, supply trends), and look at Quantitaive metrics for evidence of fraud. 
