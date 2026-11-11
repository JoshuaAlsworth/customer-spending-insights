package za.co.customerinsights;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = {
    "spring.autoconfigure.exclude=org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration,org.springframework.boot.session.jdbc.autoconfigure.JdbcSessionAutoConfiguration"
})
@AutoConfigureMockMvc
class SecurityConfigurationTest {
    @Autowired
    MockMvc mvc;

    @Test
    void healthIsPublicButOtherPathsAreDenied() throws Exception {
        assertThat(mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/actuator/health"))
            .andReturn().getResponse().getStatus()).isEqualTo(200);
        var denied = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/private"))
            .andReturn().getResponse();
        assertThat(denied.getStatus()).isEqualTo(403);
        assertThat(denied.getHeader("Set-Cookie")).isNull();
    }
}
