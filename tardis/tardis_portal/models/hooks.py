from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from tardis.tardis_portal.staging import StagingHook
from tardis.tardis_portal.tasks import verify_replica

from .experiment import Experiment, Author_Experiment
from .replica import Replica
from .parameters import ExperimentParameter, ExperimentParameterSet

import logging
logger = logging.getLogger(__name__)

### Staging hook ###

staging_hook = StagingHook()
post_save.connect(staging_hook, sender=Replica)

### RIF-CS hooks ###

def publish_public_expt_rifcs(experiment):
    try:
        providers = settings.RIFCS_PROVIDERS
    except:
        providers = None
    from tardis.tardis_portal.publish.publishservice import PublishService
    pservice = PublishService(providers, experiment)
    try:
        pservice.manage_rifcs(settings.OAI_DOCS_PATH)
    except:
        logger.error('RIF-CS publish hook failed for experiment %d.'\
                     % experiment.id)

@receiver(post_save, sender=Author_Experiment)
@receiver(post_delete, sender=Author_Experiment)
def post_save_author_experiment(sender, **kwargs):
    author_experiment = kwargs['instance']
    try:
        publish_public_expt_rifcs(author_experiment.experiment)
    except Experiment.DoesNotExist:
        # If for some reason the experiment is missing, then ignore update
        pass

@receiver(post_save, sender=ExperimentParameter)
@receiver(post_delete, sender=ExperimentParameter)
def post_save_experiment_parameter(sender, **kwargs):
    experiment_param = kwargs['instance']
    try:
        publish_public_expt_rifcs(experiment_param.parameterset.experiment)
    except ExperimentParameterSet.DoesNotExist:
        # If for some reason the experiment parameter set is missing,
        # then ignore update
        pass

@receiver(post_save, sender=Experiment)
@receiver(post_delete, sender=Experiment)
def post_save_experiment(sender, **kwargs):
    experiment = kwargs['instance']
    publish_public_expt_rifcs(experiment)

@receiver(post_save, sender=Experiment)  # THIS MUST BE DEFINED BEFORE GENERATING RIF-CS
def ensure_doi_exists(sender, **kwargs):
    experiment = kwargs['instance']
    if settings.DOI_ENABLE and experiment.public_access != Experiment.PUBLIC_ACCESS_NONE:
        doi_url = settings.DOI_BASE_URL + experiment.get_absolute_url()
        from tardis.tardis_portal.ands_doi import DOIService
        doi_service = DOIService(experiment)
        doi_service.get_or_mint_doi(doi_url)

### ApiKey hooks
if getattr(settings, 'AUTOGENERATE_API_KEY', False):
    from django.contrib.auth.models import User
    from tastypie.models import create_api_key
    post_save.connect(create_api_key, sender=User)


@receiver(post_save, sender=Replica, dispatch_uid='auto_verify_replicas')
def auto_verify_on_save(sender, **kwargs):
    '''
    auto verify local files
    reverify on every save
    '''
    replica = kwargs['instance']
    update_fields = kwargs['update_fields']
    # if save is done by the verify action, only 'verified' is updated
    # needs to be called as .save(update_fields=['verified'])
    if update_fields is not None and list(update_fields) == ['verified']:
        return
    if replica.protocol != 'staging':
        verify_replica.delay(replica.id, only_local=False, reverify=True)
