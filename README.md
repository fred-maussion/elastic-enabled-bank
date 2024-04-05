# Online banking prototype demo
The idea behind this repo is to provide an easy way to demonstrate how Elastic can improve both customer facing and 
internal bank visibility and analytics through the implementation of data de-normalization, semantic search and generative AI.

Begin by downloading this repo to your local machine or host.

Irrespective of how you deploy the python app, you will need an Elasticsearch cluster setup and running.

### Elasticsearch config: 

Your cluster will need: 
- 8GB RAM hot nodes
- 4GB RAM ml nodes
- 1GB RAM kibana node
- 2GB RAM search node
- an Integration node if you want to instrument the application later

Once you have a cluster configured, you must enable the '.elser_model_2_linux-x86_64' trained model in your cluster. If you choose another model you must consider
the implications of updating the query code as the format of the semantic search is done using text expansion.

In order for sentiment analysis to work on the LLM logging capability, you will need a sentiment model. I used 'nlptown__bert-base-multilingual-uncased-sentiment'
as this provides a score based on stars (5 being the most positive and 1 being the least) and also gives a confidence prediction out of 1.

You will need to upload this into your cluster following the ELAND library steps available here:

````
https://eland.readthedocs.io/en/latest/
````

### For the python app, you have two options in terms of proceeding, please choose your flavour: 

## Run as-is using Docker:
- Navigate to the root folder of the downloaded repo.
- using the file env.example as a template, construct your .env file with all of the necessary credentials required to run the demo.
- Note that the DJANGO_SECRET will be created at build time by the Dockerfile.

- Build the container image:
````
sudo docker build -t <your_chosen_image_name> .
````
Next, run the container and bind it to a port on the host:
````
docker run -d -p 8080:8000 <your_chosen_image_name>
````

Your host should now serve the demo on port 8080.

You can skip the next section and go straight to "Configuring the Elastic Enabled Bank" section below.

## Set up locally on your environment:
### Ideally you need to have experience with Python. 
#### This project has been designed to run locally on your own computer, connecting to an Elastic Cloud cluster, and an Azure OpenAI endpoint.

### Prerequisites
You must have Python 3.10 or above installed locally on the system you intend to run this demo on. 
In addition, please review the contents of the env.example file in this repo and ensure you have the necessary details to populate the template.
Certain credentials will be generated as you build the application. 

Specifically:

- DJANGO_SECRET_KEY - this gets created when you build your django project
All other details in the .env file will need to be obtained prior to the setup of this project.

### Installation
To begin: 
- navigate to the project root in terminal 
- create a new virtual environment.

The command to do this is: 
````
python3 -m venv <your_preferred_env_name>
````

Next, activate the virtual environment with the following command: 
````
source <your_newly_env_folder>/bin/activate
````
Once you've done this successfully you will see that your terminal input is prefixed by
  (your_env_name). This denotes that your virtual environment is active. If you want to 
deactivate it, you simply type: deactivate. 

You can learn more here: 
````
https://docs.python.org/3/library/venv.html
````

Now that your environment is active, you need to install all the project dependencies:
````
pip install -r requirements.txt
````

Once you have installed all dependencies, create your new Django project with the following command:
````
django-admin startproject config .
````
The trailing period after 'config' is **CRITICAL** so do not omit it.

### Project configuration:

Create a fresh .env file, and use the contents of env.example as a template. You will need all of these values in order for the 
application to work. 

IMPORTANT: Grab the Django Secret Key from the newly created settings.py file located in the 'config' folder, and put it in your .env file.

Next, copy the urls.py and settings.py files from the 'example-config' folder to the 'config' folder (**overwrite** the existing files)

In your terminal, enter the following command to start the webserver:
````
python manage.py runserver
````
Access the front-end of the online banking app by entering "127.0.0.1:8000" in your browser. 

And hey, look at that, we're running an ***Elastic-enabled bank!***

### Configuring the Elastic Enabled Bank:

- Start with the Environment Setup, confirm you can connect with your cluster and execute the index and pipeline builds
- In order for the ***Customer support demo*** to work, you MUST set it up manually as there is no Web Crawler API.
- This means the pipeline build must be done manually as well because you need to force the crawler to use the inference pipeline. 
There is a secondary reason for this as well: you need to choose the content source for customer support, the only prerequisite for the 
demo to work is that the title and body_content fields need to be expanded using an ELSER model.
- Next you need to generate new data, and then export that data to the Elastic cluster. I've tried really hard to make those
forms easy to understand, so I won't explain them here. What is really important is that when you export to Elastic 
just leave the process to run. If you're exporting a really huge dataset and the browser times out, then you can go back and
use the Export function again - you will not duplicate any records in Elastic as any exported records are flagged and not reimported. 
- The overall demo homepage has demo storylines with click through's, but you can just hit the Online banking portal and run your own storyline if you want to.