package za.co.customerinsights;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
class SecurityConfiguration {
    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        return http
            .requestCache(cache -> cache.disable())
            .authorizeHttpRequests(requests -> requests
                .requestMatchers("/actuator/health").permitAll()
                .anyRequest().denyAll())
            .build();
    }
}
