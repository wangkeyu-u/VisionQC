import { Redirect, Route, Switch } from 'wouter'
import { AppShell } from './components/AppShell'
import { IncidentPage } from './pages/IncidentPage'
import { InspectionPage } from './pages/InspectionPage'
import { GatewayDashboardPage } from './pages/GatewayDashboardPage'
import { ReviewQueuePage } from './pages/ReviewQueuePage'
import { ReviewWorkspacePage } from './pages/ReviewWorkspacePage'
import { UploadPage } from './pages/UploadPage'
import { OverviewPage } from './pages/OverviewPage'
import { ModelOpsPage } from './pages/ModelOpsPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { OnboardingPage } from './pages/OnboardingPage'

export function AppRoutes() {
  return (
    <AppShell>
      <Switch>
        <Route path="/" component={OverviewPage} />
        <Route path="/upload" component={UploadPage} />
        <Route path="/start" component={OnboardingPage} />
        <Route path="/inspections/:id" component={InspectionPage} />
        <Route path="/reviews" component={ReviewQueuePage} />
        <Route path="/reviews/:taskId" component={ReviewWorkspacePage} />
        <Route path="/incidents/:id" component={IncidentPage} />
        <Route path="/incidents" component={IncidentsPage} />
        <Route path="/operations" component={GatewayDashboardPage} />
        <Route path="/modelops" component={ModelOpsPage} />
        <Route><Redirect to="/" /></Route>
      </Switch>
    </AppShell>
  )
}
