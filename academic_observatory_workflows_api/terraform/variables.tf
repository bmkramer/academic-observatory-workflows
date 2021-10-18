variable "environment" {
  description = "The environment type: develop, staging or production."
  type        = string
}

variable "google_cloud" {
  description = <<EOF
The Google Cloud settings for the Observatory Platform.

project_id: the Google Cloud project id.
credentials: the path to the Google Cloud credentials.
region: the Google Cloud region.
zone: the Google Cloud zone.
data_location: the data location for storing buckets.
EOF
  type = object({
    project_id    = string
    credentials   = string
    region        = string
    zone          = string
    data_location = string
  })
}

variable "api" {
  description = <<EOF
Settings related to the API

name: Name of the API project, e.g. academic-observatory or oaebu
//package_name: Local path to the Data API package, e.g. /path/to/academic_observatory_workflows_api
domain_name: The custom domain name for the API, used for the google cloud endpoints service
subdomain: Can be either 'project_id' or 'environment', used to determine a prefix for the domain_name
image_tag: Image tag used for the Cloud Run backend service
build_info: The build info is passed on as an annotation to the Cloud Run backend service.
If this info is changed between deployments, a new revision will be created.
If the build info is an empty string, the content of a local file './image_build.txt' will be passed on as build info.
EOF
  type = object({
    name = string
//    package = string
    domain_name = string
    subdomain = string
    image_tag = string
    build_info = string
  })
}

variable "observatory_api" {
  description = <<EOF
Settings related specifically to the Observatory API
EOF
  type = object({
    observatory_organization = string
    observatory_workspace = string
  })
}

variable "data_api" {
  description = <<EOF
Settings related specifically to a Data API

api_key: The elasticsearch api key
host: The address of the elasticsearch server
EOF
  type = object({
    elasticsearch_api_key = string
    elasticsearch_host = string
  })
}