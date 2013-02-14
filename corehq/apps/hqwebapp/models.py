from django.conf import settings
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe, mark_for_escaping
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_noop

from dimagi.utils.couch.database import get_db

from corehq.apps.reports.dispatcher import ProjectReportDispatcher
from corehq.apps.adm.dispatcher import ADMSectionDispatcher
from corehq.apps.data_interfaces.dispatcher import DataInterfaceDispatcher


def format_submenu_context(title, url=None, html=None,
                           is_header=False, is_divider=False):
    return {
        'title': title,
        'url': url,
        'html': html,
        'is_header': is_header,
        'is_divider': is_divider,
    }


def format_second_level_context(title, url, menu):
    return {
        'title': title,
        'url': url,
        'is_second_level': True,
        'submenu': menu,
    }


class UITab(object):
    title = None
    view = None
    subtab_classes = None

    def __init__(self, request, domain=None, couch_user=None, project=None):
        # todo: domain object for commtrack

        if self.subtab_classes:
            self.subtabs = [cls(request, domain=domain, couch_user=couch_user,
                                project=project)
                            for cls in self.subtab_classes]
        else:
            self.subtabs = None

        self.domain = domain
        self.couch_user = couch_user
        self.project = project
       
        # This should not be considered as part of the subclass API unless it
        # is necessary. Try to add new explicit parameters instead.
        self._request = request

    
    @property
    def dropdown_items(self):
        return []

    @property
    def sidebar_items(self):
        return []
 
    @property
    def is_viewable(self):
        """
        Whether the tab should be displayed.  Subclass implementations can skip
        checking whether domain, couch_user, or project is not None before
        accessing an attribute of them -- this property is accessed in
        real_is_viewable and wrapped in a try block that returns False in the
        case of an AttributeError for any of those variables.

        """
        raise NotImplementedError()

    @property
    def real_is_viewable(self):
        if self.subtabs:
            return any(st.real_is_viewable for st in self.subtabs)
        else:
            try:
                return self.is_viewable
            except AttributeError as e:
                import re
                if not re.search('domain|couch_user|project', e.args[0]):
                    raise

                return False
    
    @property
    def url(self):
        if self.domain:
            try:
                return reverse(self.view, args=[self.domain])
            except Exception:
                pass
        
        try:
            return reverse(self.view)
        except Exception:
            return None

    @property
    def is_active(self):
        return self._request.get_full_path().startswith(self.url or "")

    @property
    def css_id(self):
        return self.__class__.__name__


class ReportsTab(UITab):
    title = ugettext_noop("Reports")
    view = "corehq.apps.reports.views.default"
    subtab_classes = (ProjectReportsTab, ADMReportsTab)


class ProjectReportsTab(UITab):
    title = ugettext_noop("Project Reports")
    view = "corehq.apps.reports.views.default"

    @property
    def is_viewable(self):
        return (self.domain and self.project and not self.project.is_snapshot and
                (self.couch_user.can_view_reports() or
                 self.couch_user.get_viewable_reports))

    @property
    def sidebar_items(self):
        context = {
            'request': self.request,
            'domain': self.domain,
        }

        project_reports = ProjectReportDispatcher.report_navigation_items(
            context)
        custom_reports = CustomProjectReportDispatcher.report_navigation_items(
            context)

        return project_reports + custom_reports


        if not adm_enabled:
            return project_reports
        else:
            adm_reports = ADMSectionDispatcher.report_navigation_items(context)
            return [
                {'title': _("Active Data Management"),
                 'active': None,
                 'url': reverse('reports_home', args=[self.domain]),
                 'items': adm_reports},
                {'title': _("Project Reports"),
                 'active': None,
                 'url': reverse('default_adm_report', args=[self.domain]),
                 'items': project_reports + custom_reports}
            ]


class ADMReportsTab(UITab):
    title = ugettext_noop("Active Data Management")
    view = "corehq.apps.adm.views.default_adm_report"

    @property
    def is_viewable(self):
        adm_enabled_projects = getattr(settings, 'ADM_ENABLED_PROJECTS', [])

        return (self.domain and not self.project.is_snapshot and 
                self.domain in adm_enabled_projects and
                  (self.couch_user.can_view_reports() or
                   self.couch_user.get_viewable_reports()))


class ProjectInfoTab(UITab):
    title = ugettext_noop("Project Info")
    view = "corehq.apps.appstore.views.project_info"

    @property
    def is_viewable(self):
        return self.project and self.project.is_snapshot


class ManageDataTab(UITab):
    title = ugettext_noop("Manage Data")
    view = "corehq.apps.data_interfaces.views.default"

    @property
    def is_viewable(self):
        return self.domain and self.couch_user.can_edit_data()

    @property
    def sidebar_items(self):
        return DataInterfaceDispatcher.report_navigation_items({
            'request': self.request,
            'domain': self.domain
        })

        
class ApplicationsTab(UITab):
    title = ugettext_noop("Applications")
    view = "corehq.apps.app_manager.views.default"

    @property
    def dropdown_items(self):
        # todo async refresh submenu when on the applications page and you change the application name
        key = [self.domain]
        apps = get_db().view('app_manager/applications_brief',
            reduce=False,
            startkey=key,
            endkey=key+[{}],
            stale='update_after',
        ).all()
        submenu_context = []
        if not apps:
            return submenu_context

        submenu_context.append(format_submenu_context(_('My Applications'), is_header=True))
        for app in apps:
            app_info = app['value']
            if app_info:
                url = reverse('view_app', args=[self.domain, app_info['_id']])
                app_name = mark_safe("%s" % mark_for_escaping(app_info['name'] or '(Untitled)'))
                submenu_context.append(format_submenu_context(app_name, url=url))

        if self.couch_user.can_edit_apps():
            submenu_context.append(format_submenu_context(None, is_divider=True))
            newapp_options = [
                format_submenu_context(None, html=self._new_app_link(_('Blank Application'))),
                format_submenu_context(None, html=self._new_app_link(_('RemoteApp (Advanced Users Only)'),
                    is_remote=True)),
            ]
            newapp_options.append(format_submenu_context(_('Visit CommCare Exchange to copy existing app...'),
                url=reverse('appstore')))
            submenu_context.append(format_second_level_context(
                _('New Application...'),
                '#',
                newapp_options
            ))
        return submenu_context

    def _new_app_link(self, title, is_remote=False):
        template = "app_manager/partials/new_app_link.html"
        return mark_safe(render_to_string(template, {
            'domain': self.domain,
            'is_remote': is_remote,
            'action_text': title,
        }))

    @property
    def is_viewable(self):
        couch_user = self.couch_user
        return (self.domain and couch_user and
                (couch_user.is_web_user() or couch_user.can_edit_apps()) and
                (couch_user.is_member_of(self.domain) or couch_user.is_superuser))


class CloudcareTab(UITab):
    title = ugettext_noop("CloudCare")
    view = "corehq.apps.cloudcare.views.default"

    @property
    def is_viewable(self):
        return self.domain and self.couch_user.can_edit_data()


class MessagesTab(UITab):
    title = ugettext_noop("Messages")
    view = "corehq.apps.sms.views.messaging"

    @property
    def is_viewable(self):
        return (self.domain and self.project and not self.project.is_snapshot and
                not self.couch_user.is_commcare_user())


class ProjectSettingsTab(UITab):
    view = "corehq.apps.users.views.users"

    @property
    def url(self):
        from corehq.apps.users.views import redirect_users_to
        return redirect_users_to(self._request, self.domain) or reverse("homepage")

    @property
    def dropdown_items(self):
        return []

    @property
    def title(self):
        if not (self.couch_user.can_edit_commcare_users() or
                self.couch_user.can_edit_web_users()):
            return _("Settings")
        return _("Settings & Users")

    @property
    def is_viewable(self):
        return self.domain and self.couch_user


class AdminReportsTab(UITab):
    title = ugettext_noop("Admin")
    view = "corehq.apps.hqadmin.views.default"

    @property
    def dropdown_items(self):
        submenu_context = [
            format_submenu_context(_("Reports"), is_header=True),
            format_submenu_context(_("Admin Reports"), url=reverse("default_admin_report")),
            format_submenu_context(_("System Info"), url=reverse("system_info")),
            format_submenu_context(_("Management"), is_header=True),
            format_submenu_context(mark_for_escaping(_("ADM Reports & Columns")),
                url=reverse("default_adm_admin_interface")),
#            format_submenu_context(mark_for_escaping("HQ Announcements"),
#                url=reverse("default_announcement_admin")),
        ]
        try:
            submenu_context.append(format_submenu_context(mark_for_escaping(_("Billing")),
                url=reverse("billing_default")))
        except Exception:
            pass
        submenu_context.extend([
            format_submenu_context(None, is_divider=True),
            format_submenu_context(_("Django Admin"), url="/admin")
        ])
        return submenu_context

    @property
    def is_viewable(self):
        return self.couch_user and self.couch_user.is_superuser


class ExchangeTab(UITab):
    title = ugettext_noop("Exchange")
    view = "corehq.apps.appstore.views.appstore"

    @property
    def dropdown_items(self):
        submenu_context = None
        if self.domain and self.couch_user.is_domain_admin(self.domain):
            submenu_context = [
                format_submenu_context(_("CommCare Exchange"), url=reverse("appstore")),
                format_submenu_context(_("Publish this project"),
                    url=reverse("domain_snapshot_settings", args=[self.domain]))
            ]
        return submenu_context

    @property
    def is_viewable(self):
        return not self.couch_user.is_commcare_user()

class ManageSurveysTab(UITab):
    title = ugettext_noop("Manage Surveys")
    view = "corehq.apps.reminders.views.sample_list"

    @property
    def is_viewable(self):
        return (self.domain and self.couch_user.can_edit_data() and
                self.project.survey_management_enabled)
